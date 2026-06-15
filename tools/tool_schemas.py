"""
OpenAI function-calling tool schemas for all 7 vessel intelligence tools.
"""

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_vessel_track",
            "description": (
                "Get the path/track of a vessel between two timestamps, "
                "as an ordered list of lat/lon points with speed and course. "
                "Use this to answer questions about where a vessel traveled."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "Vessel name or MMSI number"
                    },
                    "start_time": {
                        "type": "string",
                        "format": "date-time",
                        "description": "Start of time range (ISO 8601)"
                    },
                    "end_time": {
                        "type": "string",
                        "format": "date-time",
                        "description": "End of time range (ISO 8601)"
                    }
                },
                "required": ["identifier", "start_time", "end_time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_vessel_position_at",
            "description": (
                "Get the position of a vessel at or nearest to a specific timestamp. "
                "Returns the closest recorded position and the time difference."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "Vessel name or MMSI number"
                    },
                    "timestamp": {
                        "type": "string",
                        "format": "date-time",
                        "description": "The target timestamp (ISO 8601)"
                    }
                },
                "required": ["identifier", "timestamp"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_vessel_info",
            "description": (
                "Get static identity information about a vessel: name, MMSI, IMO, "
                "call sign, type, dimensions, and data coverage period."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "Vessel name or MMSI number"
                    }
                },
                "required": ["identifier"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_voyage",
            "description": (
                "Get a summary of a vessel's voyage over a time range: total distance, "
                "average and max speed, bounding box, start/end positions, and report count."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "Vessel name or MMSI number"
                    },
                    "start_time": {
                        "type": "string",
                        "format": "date-time",
                        "description": "Start of time range (ISO 8601)"
                    },
                    "end_time": {
                        "type": "string",
                        "format": "date-time",
                        "description": "End of time range (ISO 8601)"
                    }
                },
                "required": ["identifier", "start_time", "end_time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_vessels_near",
            "description": (
                "Find all vessels that were within a given radius of a geographic point "
                "around a specific time. Useful for proximity analysis and area monitoring."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "lat": {
                        "type": "number",
                        "description": "Latitude of the search center"
                    },
                    "lon": {
                        "type": "number",
                        "description": "Longitude of the search center"
                    },
                    "radius_km": {
                        "type": "number",
                        "description": "Search radius in kilometers"
                    },
                    "timestamp": {
                        "type": "string",
                        "format": "date-time",
                        "description": "Center of the time window (ISO 8601)"
                    },
                    "tolerance_minutes": {
                        "type": "integer",
                        "description": "Time window +/- around the timestamp (default: 15 min)",
                        "default": 15
                    }
                },
                "required": ["lat", "lon", "radius_km", "timestamp"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "detect_dark_activity",
            "description": (
                "Detect periods where a vessel stopped transmitting AIS ('went dark') "
                "within a time range. Returns gap details including duration, "
                "jump distance, and implied speed — useful for flagging suspicious activity."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "Vessel name or MMSI number"
                    },
                    "start_time": {
                        "type": "string",
                        "format": "date-time",
                        "description": "Start of time range (ISO 8601)"
                    },
                    "end_time": {
                        "type": "string",
                        "format": "date-time",
                        "description": "End of time range (ISO 8601)"
                    },
                    "gap_threshold_minutes": {
                        "type": "integer",
                        "description": "Minimum gap duration to flag (default: 30 min)",
                        "default": 30
                    }
                },
                "required": ["identifier", "start_time", "end_time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "visualize_path",
            "description": (
                "Generate an interactive map of a vessel's track with AIS gaps highlighted. "
                "Returns a path to the HTML map file. Use this when the user wants to see "
                "a visual representation of a vessel's movements."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "Vessel name or MMSI number"
                    },
                    "start_time": {
                        "type": "string",
                        "format": "date-time",
                        "description": "Start of time range (ISO 8601)"
                    },
                    "end_time": {
                        "type": "string",
                        "format": "date-time",
                        "description": "End of time range (ISO 8601)"
                    }
                },
                "required": ["identifier", "start_time", "end_time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_vessels_with_dark_activity",
            "description": (
                "List all vessels that went dark (exhibited AIS transmission gaps) "
                "within a given time range. Use this when the user asks for all vessels "
                "with dark activity or gaps."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_time": {
                        "type": "string",
                        "format": "date-time",
                        "description": "Start of time range (ISO 8601)"
                    },
                    "end_time": {
                        "type": "string",
                        "format": "date-time",
                        "description": "End of time range (ISO 8601)"
                    },
                    "min_gap_minutes": {
                        "type": "integer",
                        "description": "Minimum gap duration in minutes to filter (default: 30)",
                        "default": 30
                    }
                },
                "required": ["start_time", "end_time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_location_to_coordinates",
            "description": (
                "Resolve a named location or landmark (e.g. Seattle, Houston, New York) "
                "to its latitude and longitude. Use this before calling find_vessels_near "
                "if the user specifies a location name instead of coordinates."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location_name": {
                        "type": "string",
                        "description": "The name of the city, port, or region"
                    }
                },
                "required": ["location_name"]
            }
        }
    }
]
