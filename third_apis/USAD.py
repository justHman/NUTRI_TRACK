import requests
from typing import Dict


class USDAClient:
    """USDA FoodData Central API Client
    
    Fetches nutrition data (calories, protein, fat, carbs) for food items.
    Falls back to mock data if API key is invalid or request fails.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.nal.usda.gov/fdc/v1"

    def get_nutrition(self, query: str) -> Dict[str, float]:
        """Get nutrition info for a food query
        
        Args:
            query: Food name to search (e.g. "rice", "grilled pork")
        
        Returns:
            Dict with keys: calories, protein, fat, carbs
        """
        if not self.api_key or self.api_key == "DEMO_KEY":
            return self._get_mock_nutrition(query)
        try:
            search_url = f"{self.base_url}/foods/search"
            params = {"query": query, "pageSize": 1, "api_key": self.api_key}
            resp = requests.get(search_url, params=params)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("foods"):
                return self._get_mock_nutrition(query)
            food = data["foods"][0]
            print(food)
            nutrients = food.get("foodNutrients", [])
            print("\n\n")
            print(nutrients)
            result = {"calories": 0, "protein": 0, "fat": 0, "carbs": 0}
            for n in nutrients:
                if n.get("nutrientNumber") == "208" or n.get("nutrientName") == "Energy":
                    result["calories"] = n.get("value", 0)
                elif n.get("nutrientNumber") == "203" or n.get("nutrientName") == "Protein":
                    result["protein"] = n.get("value", 0)
                elif n.get("nutrientNumber") == "204" or n.get("nutrientName") == "Total lipid (fat)":
                    result["fat"] = n.get("value", 0)
                elif n.get("nutrientNumber") == "205" or n.get("nutrientName") == "Carbohydrate, by difference":
                    result["carbs"] = n.get("value", 0)
            return result
        except Exception:
            return self._get_mock_nutrition(query)

    def _get_mock_nutrition(self, query: str) -> Dict[str, float]:
        """Fallback mock nutrition data"""
        print(f"⚠️ Using mock nutrition for '{query}'")
        return {"calories": 150, "protein": 10, "carbs": 20, "fat": 5}


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()

    client = USDAClient(api_key=os.getenv("USDA_API_KEY"))
    result = client.get_nutrition("rice")
    print(f"Nutrition for 'rice': {result}")
