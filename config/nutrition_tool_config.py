NUTRITION_TOOL_CONFIG = {
        "tools": [
            {
                "toolSpec": {
                    "name": "get_nutrition",
                    "description": (
                        "Look up nutrition facts (calories, protein, fat, carbs per 100g) "
                        "for a food item from the USDA FoodData Central database. "
                        "Call this for each food item detected in the image."
                    ),
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "food_name": {
                                    "type": "string",
                                    "description": "Name of the food item in English (e.g., 'fried chicken', 'white rice', 'grilled pork chop')"
                                }
                            },
                            "required": ["food_name"]
                        }
                    }
                }
            }
        ]
    }