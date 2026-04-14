# Settings previously copy/pasted inside USDA, OpenFoodFacts, and AvocavoNutrition clients.

CACHE_TTL_DAYS = 30
NEGATIVE_CACHE_TTL_DAYS = 1   # "not found" entries expire after 1 day (re-tried sooner)
L1_MAXSIZE = 256
NEGATIVE_CACHEABLE_SEARCH_STATUSES = {404, 204}
