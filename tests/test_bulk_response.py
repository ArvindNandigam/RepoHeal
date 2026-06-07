from app.routes.response_formatters import format_bulk_response


def test_bulk_response_matches_symbol_response_relationship_shape():
    response = format_bulk_response([
        {
            "library": "flask",
            "status": "success",
            "result": {
                "library": "flask",
                "latest_version": "3.0.0",
                "results": [
                    {
                        "symbol": "flask.before_request",
                        "known": True,
                        "relationships": [
                            {
                                "relation": "deprecated_in_favor_of",
                                "to": "flask.before_app_request",
                                "status": "verified",
                            }
                        ],
                    }
                ],
            },
        }
    ])

    relationship = response["results"][0]["results"][0]["relationships"][0]
    assert relationship == {
        "relation": "deprecated_in_favor_of",
        "target": "flask.before_app_request",
        "status": "verified",
    }
