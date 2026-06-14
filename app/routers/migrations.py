import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from fastapi.responses import HTMLResponse
from app.auth.jwt_manager import verify_session_token
from app.auth.authorization import verify_repository_access
from app.routers.dependencies import get_session_data, ensure_repoheal_installed
from app.github.client import RepoHealGitHubClient
from app.github.metadata_branch import MetadataBranchManager
from app.migrations.compatibility_shims import check_compilation, tiered_patch_with_retry
from app.models.schemas import ApproveUpgradesRequest
from app.remediation.orchestrator import RemediationOrchestrator
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/migrations", tags=["migrations"])


@router.get("/{repo_owner}/{repo_name}")
async def list_migrations(
    repo_owner: str,
    repo_name: str,
    status: Optional[str] = Query(None),
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    installation = ensure_repoheal_installed(repo_owner, repo_name)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )

    client = RepoHealGitHubClient(installation["id"])
    repo = client.get_repo(f"{repo_owner}/{repo_name}")
    metadata_manager = MetadataBranchManager(client)
    manifest = metadata_manager._load_manifest(repo)

    migrations = manifest.get("migration_reports", [])
    if isinstance(migrations, list):
        if status:
            migrations = [m for m in migrations if m.get("status", "completed") == status]
        return {"migrations": migrations, "repository": f"{repo_owner}/{repo_name}"}
    return {"migrations": [], "repository": f"{repo_owner}/{repo_name}"}


@router.get("/detail/{migration_id}")
async def get_migration(
    migration_id: str,
    repo_owner: str = Query(...),
    repo_name: str = Query(...),
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    installation = ensure_repoheal_installed(repo_owner, repo_name)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )

    client = RepoHealGitHubClient(installation["id"])
    repo = client.get_repo(f"{repo_owner}/{repo_name}")
    metadata_manager = MetadataBranchManager(client)
    manifest = metadata_manager._load_manifest(repo)

    for mig in manifest.get("migration_reports", []):
        if mig.get("migration_id") == migration_id or mig.get("analysis_id") == migration_id:
            try:
                content = repo.get_contents(mig["path"], ref=metadata_manager.branch_name)
                return {
                    "migration_id": mig.get("migration_id"),
                    "analysis_id": mig.get("analysis_id"),
                    "timestamp": mig.get("timestamp"),
                    "risk_score": mig.get("risk_score"),
                    "status": mig.get("status", "completed"),
                    "path": mig["path"],
                    "content": content.decoded_content.decode("utf-8")
                }
            except Exception as e:
                return {
                    "migration_id": mig.get("migration_id"),
                    "analysis_id": mig.get("analysis_id"),
                    "timestamp": mig.get("timestamp"),
                    "risk_score": mig.get("risk_score"),
                    "status": mig.get("status", "completed"),
                    "path": mig["path"]
                }

    raise HTTPException(status_code=404, detail="Migration not found")


def _update_requirements_txt(content: str, upgrades: List[Dict]) -> str:
    """Bump version numbers in requirements.txt."""
    lines = content.split("\n")
    for lib in upgrades:
        name = lib["library"].lower()
        new_ver = lib["to_version"]
        pattern = re.compile(
            rf"^{re.escape(name)}\s*[~<>=!]+\s*[\d.*]+",
            re.IGNORECASE
        )
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("-"):
                continue
            eq_idx = stripped.find("=")
            if eq_idx == -1:
                continue
            pkg_name = stripped[:eq_idx].strip().lower()
            if pkg_name == name:
                lines[i] = f"{name}=={new_ver}"
                break
    return "\n".join(lines)


@router.post("/{repo_owner}/{repo_name}/approve-upgrades")
async def approve_upgrades(
    repo_owner: str,
    repo_name: str,
    body: ApproveUpgradesRequest = Body(...),
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    installation = ensure_repoheal_installed(repo_owner, repo_name)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )

    repo_id = f"{repo_owner}/{repo_name}"
    client = RepoHealGitHubClient(installation["id"])
    repo = client.get_repo(repo_id)

    results = []

    # Cache: read all Python source files once
    py_files_cached = []
    llm_provider = None
    try:
        contents_tree = repo.get_contents("", ref=repo.default_branch)
        if isinstance(contents_tree, list):
            for item in contents_tree:
                if item.name.endswith(".py") and item.name != "repoheal_fixes.py":
                    try:
                        src = repo.get_contents(item.path, ref=repo.default_branch)
                        py_files_cached.append((item.path, src.decoded_content.decode("utf-8"), src.sha))
                    except Exception:
                        pass
        from app.llm.base import create_llm_provider, LLMConfig
        llm_provider = create_llm_provider(LLMConfig())
    except Exception:
        pass

    for upgrade in body.upgrades:
        lib = upgrade.library
        from_ver = upgrade.from_version
        to_ver = upgrade.to_version
        branch_name = f"repoheal/upgrade-{lib.lower()}-{to_ver}"

        # Scoped per upgrade — each library gets its own PR
        modified_files = {}
        local_human_review = []

        # ── Step 1: Bump requirements.txt ──────────────────────────────
        try:
            req_contents = repo.get_contents("requirements.txt", ref=repo.default_branch)
            original_req = req_contents.decoded_content.decode("utf-8")
        except Exception:
            results.append({"library": lib, "status": "failed",
                            "error": "requirements.txt not found on default branch"})
            continue

        updated_req = _update_requirements_txt(original_req, [{"library": lib, "to_version": to_ver}])
        if updated_req == original_req:
            results.append({"library": lib, "status": "skipped",
                            "error": f"{lib} not found in requirements.txt"})
            continue

        # ── Step 2: Find & patch deprecated API usages in source files ─
        try:
            from app.intelligence.local_deprecation import lookup_replacement, LOCAL_KNOWLEDGE
            for file_path, source, sha in py_files_cached:
                if lib.lower() not in source.lower():
                    continue

                local_entries = LOCAL_KNOWLEDGE.get(lib, [])
                matched_syms = set()
                for entry in local_entries:
                    for pat in entry["match_patterns"]:
                        if pat.lower() in source.lower():
                            matched_syms.add(entry["symbol"])

                import_regex = re.compile(
                    rf"(?:from\s+{re.escape(lib)}\s+import\s+\w*|import\s+{re.escape(lib)}\s+)",
                    re.IGNORECASE
                )
                if not matched_syms and not import_regex.search(source):
                    continue

                for sym in sorted(matched_syms):
                    replacement = lookup_replacement(lib, sym)
                    patched, tier = await tiered_patch_with_retry(
                        original_code=source, symbol=sym, library=lib,
                        replacement=replacement, llm_provider=llm_provider,
                        max_groq_attempts=3,
                    )
                    if patched:
                        modified_files[file_path] = patched
                        if tier == "human_review":
                            local_human_review.append({"file": file_path, "symbol": sym})
        except Exception as e:
            logger.warning(f"Source patching error for {lib}: {e}")

        # ── Step 3: Commit all changes ─────────────────────────────────
        try:
            client.ensure_branch(repo, branch_name)

            repo.update_file("requirements.txt",
                             f"RepoHeal: upgrade {lib} {from_ver} → {to_ver}",
                             updated_req, sha=req_contents.sha, branch=branch_name)

            for fpath, patched_code in modified_files.items():
                try:
                    existing = repo.get_contents(fpath, ref=branch_name)
                    repo.update_file(fpath, f"RepoHeal: auto-patch {lib} deprecations",
                                     patched_code, sha=existing.sha, branch=branch_name)
                except Exception:
                    repo.create_file(fpath, f"RepoHeal: auto-patch {lib} deprecations",
                                     patched_code, branch=branch_name)

            # Write/compat repoheal_fixes.py for APIs with no replacement
            try:
                fixes_content = repo.get_contents("repoheal_fixes.py", ref=branch_name)
            except Exception:
                fixes_content = None
            from app.migrations.compatibility_shims import SHIM_HEADER
            shim_footer = "\n# Auto-generated by RepoHeal for compatibility.\n"
            if fixes_content:
                repo.update_file("repoheal_fixes.py", f"RepoHeal: shims for {lib}",
                                 fixes_content.decoded_content.decode("utf-8") + shim_footer,
                                 sha=fixes_content.sha, branch=branch_name)
            else:
                repo.create_file("repoheal_fixes.py", f"RepoHeal: shims for {lib}",
                                 SHIM_HEADER + shim_footer, branch=branch_name)
        except Exception as e:
            results.append({"library": lib, "status": "failed", "error": str(e)})
            continue

        # ── Step 4: Determine PR tier from compilation status ──────────
        compilations = {}
        for fpath, code in modified_files.items():
            if fpath.endswith(".py"):
                ok, err = check_compilation(code, filename=fpath)
                compilations[fpath] = (ok, err)

        py_files_patched = [f for f in modified_files if f.endswith(".py")]
        all_compile_ok = all(compilations.get(f, (True, None))[0] for f in py_files_patched) if py_files_patched else True
        has_human_needed = len(local_human_review) > 0

        if has_human_needed:
            merge_tier, is_draft, auto_merge_now = "human_review", True, False
        elif all_compile_ok and py_files_patched:
            merge_tier, is_draft, auto_merge_now = "auto_merge", False, body.auto_merge
        elif py_files_patched:
            merge_tier, is_draft, auto_merge_now = "draft_pr", True, False
        else:
            merge_tier, is_draft, auto_merge_now = "auto_merge", False, body.auto_merge

        title = f"[RepoHeal] Upgrade {lib} {from_ver} → {to_ver}"
        body_lines = [f"## Auto-Upgrade: {lib}", "", f"**{from_ver} → {to_ver}**", "",
                       "### Changes", f"- `requirements.txt`: bumped `{lib}` from `{from_ver}` to `{to_ver}`"]
        for fpath in modified_files:
            body_lines.append(f"- `{fpath}`: patched deprecated API usages")
        if py_files_patched:
            body_lines.extend(["", "### Compilation Check"])
            for fpath, (ok, err) in compilations.items():
                icon = "✓" if ok else "✗"
                body_lines.append(f"- {icon} `{fpath}`{' — ' + err if err else ''}")
        if has_human_needed:
            body_lines.extend(["", "### ⚠️ Human Review Required",
                                "Some deprecated APIs could not be auto-patched after 3 attempts."])
            for item in local_human_review:
                body_lines.append(f"- `{item['symbol']}` in `{item['file']}`")
        body_lines.append(f"\n---\n*Generated by RepoHeal — Merge tier: {merge_tier}*")

        try:
            pr = repo.create_pull(
                title=title,
                body="\n".join(body_lines),
                head=branch_name,
                base=repo.default_branch,
                draft=is_draft
            )
            if auto_merge_now:
                try:
                    pr.merge(merge_method="squash")
                except Exception:
                    pass
            results.append({
                "library": lib, "status": merge_tier,
                "pr_number": pr.number, "pr_url": pr.html_url,
                "branch": branch_name, "files_patched": len(modified_files),
            })
        except Exception as e:
            results.append({
                "library": lib, "status": "branch_created",
                "error": str(e), "branch": branch_name
            })

        # ── Step 5: Email notification for human review ────────────────
        if has_human_needed:
            try:
                from app.notifications.email_sender import _send_email
                user_email = session_data.get("github_email") or session_data.get("email", "")
                if user_email:
                    subject = f"[RepoHeal] Manual review needed for {repo_id}"
                    text = (
                        f"RepoHeal could not fully auto-patch {lib} in {repo_id}.\n\n"
                        f"PR #{pr.number}: {pr.html_url}\n\n"
                        f"The following symbols require manual attention:\n"
                        + "\n".join(f"  - {i['symbol']} in {i['file']}" for i in local_human_review)
                        + "\n\nPlease review and fix manually."
                    )
                    _send_email(user_email, subject, text, text.replace("\n", "<br>"))
            except Exception:
                pass

    # Trigger re-analysis
    try:
        from app.worker.task_registry import create_job
        job_id = create_job(repo_owner, repo_name, force=True, job_type="upgrade")
        if job_id:
            from app.worker.task_registry import run_analysis_in_background
            run_analysis_in_background(job_id)
    except Exception:
        pass

    return {"repository": repo_id, "results": results}


@router.post("/{migration_id}/approve")
async def approve_migration(
    migration_id: str,
    repo_owner: str = Query(...),
    repo_name: str = Query(...),
    symbols: str = Query(None, description="Comma-separated list of symbols to patch (omit for all)"),
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    installation = ensure_repoheal_installed(repo_owner, repo_name)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )

    repo_id = f"{repo_owner}/{repo_name}"
    client = RepoHealGitHubClient(installation["id"])
    repo = client.get_repo(repo_id)
    metadata_manager = MetadataBranchManager(client)
    manifest = metadata_manager._load_manifest(repo)

    mig_meta = None
    for mig in manifest.get("migration_reports", []):
        if mig.get("migration_id") == migration_id or mig.get("analysis_id") == migration_id:
            mig_meta = mig
            break

    if not mig_meta:
        raise HTTPException(status_code=404, detail="Migration not found")

    mig_meta["status"] = "approved"
    mig_meta["approved_at"] = datetime.now(timezone.utc).isoformat()

    files = {"repoheal.meta/metadata.json": metadata_manager._json(manifest)}
    client.batch_upsert_files(repo, metadata_manager.branch_name, files, f"Approve {migration_id}")

    risk_score = mig_meta.get("risk_score", 50)
    try:
        # Load the migration document content to extract libraries/symbols needing patching
        mig_path = mig_meta.get("path", "")
        doc_content = ""
        if mig_path:
            try:
                content = repo.get_contents(mig_path, ref=metadata_manager.branch_name)
                doc_content = content.decoded_content.decode("utf-8")
            except Exception:
                pass

        # Parse migration document for library references
        libs_found = set()
        symbols_filter = {s.strip() for s in symbols.split(",")} if symbols else None
        for line in doc_content.splitlines():
            m = re.match(r"^[*-]\s+`(\w+(?:[-\w]*\w)?)`", line)
            if m:
                libs_found.add(m.group(1).lower())

        # Apply patches via the same mechanism as approve_upgrades
        from app.intelligence.local_deprecation import lookup_replacement, LOCAL_KNOWLEDGE
        llm_provider = None
        try:
            from app.llm.base import create_llm_provider, LLMConfig
            llm_provider = create_llm_provider(LLMConfig())
        except Exception:
            pass

        modified_files = {}
        py_files_cached = []
        try:
            contents_tree = repo.get_contents("", ref=repo.default_branch)
            if isinstance(contents_tree, list):
                for item in contents_tree:
                    if item.name.endswith(".py") and item.name != "repoheal_fixes.py":
                        try:
                            src = repo.get_contents(item.path, ref=repo.default_branch)
                            py_files_cached.append((item.path, src.decoded_content.decode("utf-8"), src.sha))
                        except Exception:
                            pass
        except Exception:
            pass

        for lib in libs_found:
            local_entries = LOCAL_KNOWLEDGE.get(lib, [])
            for file_path, source, sha in py_files_cached:
                if lib not in source.lower():
                    continue
                matched_syms = set()
                for entry in local_entries:
                    for pat in entry["match_patterns"]:
                        if pat.lower() in source.lower():
                            matched_syms.add(entry["symbol"])
                import_regex = re.compile(
                    rf"(?:from\s+{re.escape(lib)}\s+import\s+\w*|import\s+{re.escape(lib)}\s+)",
                    re.IGNORECASE
                )
                if not matched_syms and not import_regex.search(source):
                    continue
                if symbols_filter:
                    matched_syms = {s for s in matched_syms if s in symbols_filter}
                if not matched_syms:
                    continue
                for sym in sorted(matched_syms):
                    replacement = lookup_replacement(lib, sym)
                    patched, tier = await tiered_patch_with_retry(
                        original_code=source, symbol=sym, library=lib,
                        replacement=replacement, llm_provider=llm_provider,
                        max_groq_attempts=3,
                    )
                    if patched:
                        modified_files[file_path] = patched

        if not modified_files:
            return {"status": "approved", "migration_id": migration_id, "pr_created": False, "message": "No patchable symbols found in migration document"}

        # Commit changes to a branch and create PR
        from app.github.changes_branch import ChangesBranchManager
        branch_manager = ChangesBranchManager(client)
        safe_mig_id = migration_id.replace("mig_", "").split("_")[0] if migration_id.startswith("mig_") else migration_id
        branches = []
        for fpath in modified_files:
            safe_name = fpath.split("/")[-1].replace(".py", "").replace(".", "_")
            branch_name = branch_manager.create_changes_branch(repo, f"{migration_id}_{safe_name}")
            branch_manager.batch_commit_changes(
                repo, branch_name, {fpath: modified_files[fpath]},
                f"RepoHeal: {migration_id} - {fpath}"
            )
            branches.append(branch_name)

        title = f"[RepoHeal] Apply migration {migration_id}"
        body_parts = [f"## Migration: {migration_id}", "", "### Changes"]
        for fpath in modified_files:
            body_parts.append(f"- `{fpath}`: patched deprecated API usages")
        body_parts.append(f"\n---\n*Generated by RepoHeal — Approved migration*")

        prs = []
        for i, (fpath, branch_name) in enumerate(zip(modified_files.keys(), branches)):
            pr = repo.create_pull(
                title=title,
                body="\n".join(body_parts),
                head=branch_name,
                base=repo.default_branch,
                draft=(risk_score > 70 if risk_score else False),
            )
            prs.append({"pr_number": pr.number, "pr_url": pr.html_url})

        return {
            "status": "approved", "migration_id": migration_id, "pr_created": True,
            "prs": prs, "files_patched": len(modified_files),
        }
    except Exception as e:
        logger.error(f"PR creation failed for approved migration {migration_id}: {e}")
        return {"status": "approved", "migration_id": migration_id, "pr_created": False, "error": str(e)}


@router.post("/{migration_id}/reject")
async def reject_migration(
    migration_id: str,
    repo_owner: str = Query(...),
    repo_name: str = Query(...),
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    installation = ensure_repoheal_installed(repo_owner, repo_name)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )

    client = RepoHealGitHubClient(installation["id"])
    repo = client.get_repo(f"{repo_owner}/{repo_name}")
    metadata_manager = MetadataBranchManager(client)
    manifest = metadata_manager._load_manifest(repo)

    for mig in manifest.get("migration_reports", []):
        if mig.get("migration_id") == migration_id or mig.get("analysis_id") == migration_id:
            mig["status"] = "rejected"
            mig["rejected_at"] = datetime.now(timezone.utc).isoformat()
            files = {"repoheal.meta/metadata.json": metadata_manager._json(manifest)}
            client.batch_upsert_files(repo, metadata_manager.branch_name, files, f"Reject {migration_id}")
            return {"status": "rejected", "migration_id": migration_id}

    raise HTTPException(status_code=404, detail="Migration not found")


@router.post("/{migration_id}/defer")
async def defer_migration(
    migration_id: str,
    repo_owner: str = Query(...),
    repo_name: str = Query(...),
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    installation = ensure_repoheal_installed(repo_owner, repo_name)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )

    client = RepoHealGitHubClient(installation["id"])
    repo = client.get_repo(f"{repo_owner}/{repo_name}")
    metadata_manager = MetadataBranchManager(client)
    manifest = metadata_manager._load_manifest(repo)

    for mig in manifest.get("migration_reports", []):
        if mig.get("migration_id") == migration_id or mig.get("analysis_id") == migration_id:
            mig["status"] = "deferred"
            mig["deferred_at"] = datetime.now(timezone.utc).isoformat()
        files = {"repoheal.meta/metadata.json": metadata_manager._json(manifest)}
        client.batch_upsert_files(repo, metadata_manager.branch_name, files, f"Defer {migration_id}")
        return {"status": "deferred", "migration_id": migration_id}

    raise HTTPException(status_code=404, detail="Migration not found")


