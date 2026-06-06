from app.analysis.package_normalization import normalize_package_name

def generate_fingerprints(semantic_graph, dependencies):
    """
    Extract unique external API symbols from the semantic graph
    and group them by root library, attaching the detected version.
    """
    fingerprints = {}
    
    files = semantic_graph.get("files", {})
    
    for file_path, file_data in files.items():
        apis = file_data.get("apis", [])
        
        for api in apis:
            package = api.get("package")
            api_name = api.get("name")
            
            if not package or not api_name:
                continue
                
            normalized_pkg = normalize_package_name(package)
            
            if normalized_pkg not in fingerprints:
                # get dependency version if available
                dep_info = dependencies.get(normalized_pkg, {})
                version = dep_info.get("version", "unknown")
                
                fingerprints[normalized_pkg] = {
                    "version": version,
                    "symbols": set()
                }
            
            fingerprints[normalized_pkg]["symbols"].add(api_name)
            
    # Convert sets to sorted lists for JSON serialization
    for pkg, data in fingerprints.items():
        data["symbols"] = sorted(list(data["symbols"]))
        
    return fingerprints
