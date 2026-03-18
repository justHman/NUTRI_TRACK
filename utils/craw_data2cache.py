"""Prefill local cache files using all three nutrition clients.

This script intentionally uses:
  - search_best() for ingredient-based warming
  - search_by_barcode() for barcode-based warming

Targets:
  - 100 common ingredient queries
  - 100 validated barcode codes (best effort)

Usage:
  python app/utils/craw_data2cache.py
  python app/utils/craw_data2cache.py --ingredient-limit 100 --barcode-target 100 --sleep 0.1
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from dotenv import load_dotenv


# Make script runnable from repo root or app root.
APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parent
if str(APP_ROOT) not in sys.path:
	sys.path.insert(0, str(APP_ROOT))

from config.logging_config import get_logger
from third_apis.AvocavoNutrition import AvocavoNutritionClient
from third_apis.OpenFoodFacts import OpenFoodFactsClient
from third_apis.USDA import USDAClient


logger = get_logger(__name__)


def _load_environment() -> None:
	"""Load environment variables from common project .env locations."""
	dotenv_candidates = [
		APP_ROOT / "config" / ".env",
	]
	for dotenv_path in dotenv_candidates:
		if dotenv_path.exists():
			load_dotenv(dotenv_path=dotenv_path, override=False)
			logger.info("Loaded .env from %s", dotenv_path)
			break
	else:
		logger.warning("No .env file found in expected locations: %s", [str(p) for p in dotenv_candidates])


# Exactly 100 common ingredient queries.
INGREDIENT_QUERIES = [
"gạo", "bún", "phở", "miến", "mì gói", "bánh mì", "bánh tráng", "bánh phở", "bánh đa", "bột năng",
"bột mì", "bột gạo", "bột bắp", "đậu hũ", "đậu xanh", "đậu đỏ", "đậu phộng", "mè", "hạt sen", "hạt điều",
"thịt heo", "thịt bò", "thịt gà", "thịt vịt", "thịt bằm", "sườn heo", "chả lụa", "giò thủ", "xúc xích", "lạp xưởng",
"tôm", "cá basa", "cá tra", "cá thu", "cá hồi", "mực", "bạch tuộc", "cua", "ghẹ", "nghêu",
"trứng gà", "trứng vịt", "trứng cút", "sữa tươi", "sữa đặc", "sữa chua", "bơ", "phô mai", "kem tươi", "sữa đậu nành",
"nước mắm", "nước tương", "tương ớt", "tương cà", "dầu ăn", "dầu mè", "dầu hào", "muối", "đường", "bột ngọt",
"hạt nêm", "tiêu", "ớt", "tỏi", "hành tím", "hành lá", "gừng", "sả", "riềng", "lá chanh",
"rau muống", "rau cải", "rau dền", "cải thảo", "bắp cải", "cà rốt", "khoai tây", "khoai lang", "củ cải", "cà chua",
"dưa leo", "bí đỏ", "bí xanh", "mướp", "khổ qua", "đậu bắp", "nấm rơm", "nấm kim châm", "nấm đông cô", "giá đỗ",
"chuối", "xoài", "đu đủ", "dứa", "cam", "quýt", "chanh", "thanh long", "vải", "nhãn"
]

BARCODE_SEEDS = [
"8938505974191","8934588013057","8934588590305","8936037368039","8934673050011",
"8934588592224","8934684013050","8934822901331","8936017368010","8934684012015",
"8936036020006","8934588010018","8938505973057","8936037368015","8934822900013",
"8934588591005","8934673050028","8936037368022","8938505971015","8934822900020",
"8934588010025","8934684012022","8936036020013","8938505971022","8934588591012",
"8936037368046","8934822900037","8934588010032","8934684012039","8936036020020",
"8938505971039","8934588591029","8936037368053","8934822900044","8934588010049",
"8934684012046","8936036020037","8938505971046","8934588591036","8936037368060",
"8934822900051","8934588010056","8934684012053","8936036020044","8938505971053",
"8934588591043","8936037368077","8934822900068","8934588010063","8934684012060",
"8936036020051","8938505971060","8934588591050","8936037368084","8934822900075",
"8934588010070","8934684012077","8936036020068","8938505971077","8934588591067",
"8936037368091","8934822900082","8934588010087","8934684012084","8936036020075",
"8938505971084","8934588591074","8936037368107","8934822900099","8934588010094",
"8934684012091","8936036020082","8938505971091","8934588591081","8936037368114",
"8934822900105","8934588010100","8934684012107","8936036020099","8938505971107",
"8934588591098","8936037368121","8934822900112","8934588010117","8934684012114",
"8936036020105","8938505971114","8934588591104","8936037368138","8934822900129",
"8934588010124","8934684012121","8936036020112","8938505971121","8934588591111"
]

INGREDIENT_QUERIES_EN = [
"rice", "rice vermicelli", "pho noodles", "glass noodles", "instant noodles", "bread", "rice paper", "pho rice sheets", "vietnamese thick noodles", "tapioca starch",
"wheat flour", "rice flour", "corn starch", "tofu", "mung beans", "red beans", "peanuts", "sesame seeds", "lotus seeds", "cashew nuts",
"pork", "beef", "chicken", "duck", "minced pork", "pork ribs", "vietnamese pork sausage", "head cheese", "sausages", "lap cheong",
"shrimp", "basa fish", "pangasius fish", "mackerel", "salmon", "squid", "octopus", "crab", "blue swimmer crab", "clams",
"chicken eggs", "duck eggs", "quail eggs", "fresh milk", "condensed milk", "yogurt", "butter", "cheese", "whipping cream", "soy milk",
"fish sauce", "soy sauce", "chili sauce", "ketchup", "cooking oil", "sesame oil", "oyster sauce", "salt", "sugar", "msg",
"seasoning powder", "black pepper", "chili pepper", "garlic", "shallots", "green onions", "ginger", "lemongrass", "galangal", "kaffir lime leaves",
"water spinach", "mustard greens", "amaranth greens", "napa cabbage", "cabbage", "carrot", "potato", "sweet potato", "daikon radish", "tomato",
"cucumber", "pumpkin", "winter melon", "luffa", "bitter melon", "okra", "straw mushroom", "enoki mushroom", "shiitake mushroom", "bean sprouts",
"banana", "mango", "papaya", "pineapple", "orange", "mandarin", "lime", "dragon fruit", "lychee", "longan"
]

INGREDIENT_QUERIES_WORLD = [
"apple","banana","orange","grape","strawberry","blueberry","raspberry","pear","peach","plum",
"pineapple","mango","papaya","kiwi","watermelon","melon","avocado","lemon","lime","coconut",
"tomato","onion","garlic","ginger","carrot","potato","sweet potato","corn","broccoli","cauliflower",
"spinach","lettuce","cabbage","kale","zucchini","eggplant","bell pepper","chili pepper","mushroom","asparagus",
"green beans","peas","chickpeas","lentils","black beans","kidney beans","soybeans","tofu","tempeh","edamame",
"rice","brown rice","quinoa","oats","barley","wheat","pasta","noodles","bread","bagel",
"croissant","pancake","waffle","pizza","burger","sandwich","hot dog","fried chicken","steak","bacon",
"ham","sausage","salami","turkey","chicken breast","ground beef","pork chops","lamb","duck","shrimp",
"salmon","tuna","cod","sardines","anchovies","milk","cheese","yogurt","butter","cream",
"egg","honey","sugar","brown sugar","maple syrup","olive oil","vegetable oil","soy sauce","vinegar","mustard"
]

BARCODE_SEEDS_WORLD = [
"0123456789012","0012345678905","0301234567896","0456789012345","0498765432109",
"0501234567890","0601234567897","0701234567894","0801234567891","0901234567898",
"1001234567895","1101234567892","1201234567899","1301234567896","2001234567893",
"2101234567890","2201234567897","2301234567894","2401234567891","2501234567898",
"3001234567894","3012345678900","3201234567898","3301234567895","3401234567892",
"3501234567899","3601234567896","3701234567893","3801234567890","4001234567897",
"4012345678903","4201234567891","4301234567898","4401234567895","4501234567892",
"4601234567899","4701234567896","4801234567893","4901234567890","5001234567897",
"5012345678906","5201234567894","5301234567891","5401234567898","5601234567892",
"5701234567899","5901234567893","6001234567897","6012345678904","6201234567898",
"6401234567892","6901234567896","6912345678902","6921234567899","7001234567895",
"7291234567892","7301234567899","7401234567896","7501234567893","7601234567890",
"7701234567897","7801234567894","7891234567891","8001234567898","8012345678902",
"8201234567896","8301234567893","8401234567890","8501234567897","8601234567894",
"8701234567891","8801234567898","8851234567892","8901234567899","8931234567896",
"9001234567890","9012345678906","9301234567894","9401234567891","9501234567898",
"9551234567892","9581234567899","9601234567893","9701234567890","9781234567897",
"9791234567894","9801234567891","9811234567898","9821234567895","9831234567892",
"9841234567899","9851234567896","9861234567893","9871234567890","9881234567897"
]

INGREDIENT_QUERIES_KOREAN = [
"kimchi","napa cabbage kimchi","radish kimchi","cucumber kimchi","kimchi stew","doenjang stew","soybean paste",
"gochujang","gochugaru","soy sauce","sesame oil","sesame seeds","garlic","ginger","green onion","perilla leaves",
"napa cabbage","korean radish","cucumber","zucchini","bean sprouts","spinach","shiitake mushroom","enoki mushroom",
"king oyster mushroom","tofu","fish cake","rice cake","tteokbokki rice cake","glass noodles","sweet potato noodles",
"ramyeon noodles","udon noodles","rice","brown rice","mixed grain rice","barley","sweet potato","potato","corn",
"egg","quail egg","chicken","chicken thigh","chicken breast","pork belly","pork shoulder","pork cutlet","beef bulgogi",
"beef short ribs","ground beef","beef brisket","beef bone","duck","squid","octopus","shrimp","crab","mackerel",
"pollock","anchovy","tuna","salmon","seaweed","dried seaweed","kelp","sea mustard","perilla oil","cooking oil",
"sugar","brown sugar","honey","corn syrup","rice syrup","vinegar","apple vinegar","black vinegar","salt","black pepper",
"milk","yogurt","cheese","butter","cream","ice cream","banana milk","strawberry milk","chocolate milk","instant coffee",
"green tea","barley tea","citron tea","ginseng tea","yakult probiotic drink","soju flavor syrup","ramen seasoning","curry powder","tempura flour","pancake mix"
]

BARCODE_SEEDS_KOREAN = [
"8801007000010","8801007000027","8801007000034","8801007000041","8801007000058",
"8801007000065","8801007000072","8801007000089","8801007000096","8801007000102",
"8801007000119","8801007000126","8801007000133","8801007000140","8801007000157",
"8801007000164","8801007000171","8801007000188","8801007000195","8801007000201",
"8801007000218","8801007000225","8801007000232","8801007000249","8801007000256",
"8801007000263","8801007000270","8801007000287","8801007000294","8801007000300",
"8801007000317","8801007000324","8801007000331","8801007000348","8801007000355",
"8801007000362","8801007000379","8801007000386","8801007000393","8801007000409",
"8801007000416","8801007000423","8801007000430","8801007000447","8801007000454",
"8801007000461","8801007000478","8801007000485","8801007000492","8801007000508",
"8801007000515","8801007000522","8801007000539","8801007000546","8801007000553",
"8801007000560","8801007000577","8801007000584","8801007000591","8801007000607",
"8801007000614","8801007000621","8801007000638","8801007000645","8801007000652",
"8801007000669","8801007000676","8801007000683","8801007000690","8801007000706",
"8801007000713","8801007000720","8801007000737","8801007000744","8801007000751",
"8801007000768","8801007000775","8801007000782","8801007000799","8801007000805",
"8801007000812","8801007000829","8801007000836","8801007000843","8801007000850",
"8801007000867","8801007000874","8801007000881","8801007000898","8801007000904",
"8801007000911","8801007000928","8801007000935","8801007000942","8801007000959",
"8801007000966","8801007000973","8801007000980","8801007000997","8801007001000"
]

INGREDIENT_QUERIES_japan = [
"sushi","sashimi","ramen","udon","soba","tempura","tonkatsu","okonomiyaki","takoyaki","onigiri",
"miso soup","miso paste","soy sauce","mirin","sake","rice vinegar","dashi","kombu","katsuobushi","nori",
"wakame","tofu","aburaage","natto","tamago","japanese rice","brown rice","mochi","rice crackers","anko",
"matcha","green tea","hojicha","genmaicha","japanese curry","curry roux","yakitori","teriyaki chicken","beef bowl","gyudon",
"oyakodon","katsudon","tempura shrimp","shrimp","salmon","tuna","yellowtail","mackerel","eel","squid",
"octopus","scallops","crab","fish cake","kamaboko","chikuwa","daikon radish","lotus root","burdock root","shiitake mushroom",
"enoki mushroom","king oyster mushroom","shimeji mushroom","bamboo shoots","spinach","japanese cucumber","eggplant","sweet potato","kabocha pumpkin","potato",
"carrot","onion","garlic","ginger","green onion","wasabi","pickled ginger","pickled plum","tsukemono","seaweed salad",
"milk","yogurt","butter","cheese","whipping cream","egg","sugar","brown sugar","honey","sesame seeds",
"sesame oil","vegetable oil","tempura flour","panko breadcrumbs","instant ramen","ramen seasoning","udon noodles","soba noodles","mochi ice cream","dorayaki"
]

BARCODE_SEEDS_japan = [
"4501234567890","4501234567897","4501234567807","4501234567814","4501234567821",
"4501234567838","4501234567845","4501234567852","4501234567869","4501234567876",
"4511234567893","4511234567890","4511234567886","4511234567879","4511234567862",
"4521234567896","4521234567893","4521234567889","4521234567872","4521234567865",
"4531234567899","4531234567896","4531234567882","4531234567875","4531234567868",
"4541234567892","4541234567899","4541234567885","4541234567878","4541234567861",
"4551234567895","4551234567892","4551234567888","4551234567871","4551234567864",
"4561234567898","4561234567895","4561234567881","4561234567874","4561234567867",
"4571234567891","4571234567898","4571234567884","4571234567877","4571234567860",
"4581234567894","4581234567891","4581234567887","4581234567870","4581234567863",
"4591234567897","4591234567894","4591234567880","4591234567873","4591234567866",
"4509876543210","4509876543217","4509876543224","4509876543231","4509876543248",
"4519876543213","4519876543210","4519876543227","4519876543234","4519876543241",
"4529876543216","4529876543213","4529876543220","4529876543237","4529876543244",
"4539876543219","4539876543216","4539876543223","4539876543230","4539876543247",
"4549876543212","4549876543219","4549876543226","4549876543233","4549876543240",
"4559876543215","4559876543212","4559876543229","4559876543236","4559876543243",
"4569876543218","4569876543215","4569876543222","4569876543239","4569876543246",
"4579876543211","4579876543218","4579876543225","4579876543232","4579876543249",
"4589876543214","4589876543211","4589876543228","4589876543235","4589876543242",
"4599876543217","4599876543214","4599876543221","4599876543238","4599876543245"
]

INGREDIENT_QUERIES_china = [
"fried rice","chow mein","lo mein","dumplings","wontons","spring rolls","egg rolls","baozi","mantou","xiaolongbao",
"hot pot","mapo tofu","kung pao chicken","sweet and sour pork","peking duck","char siu","dan dan noodles","biang biang noodles","lamian","rice noodles",
"soy sauce","dark soy sauce","light soy sauce","oyster sauce","hoisin sauce","black bean sauce","chili oil","chili paste","sesame oil","rice vinegar",
"black vinegar","five spice powder","sichuan peppercorn","star anise","ginger","garlic","green onion","shallots","dried chili","white pepper",
"tofu","silken tofu","fried tofu","tofu skin","bean curd sticks","soybeans","mung beans","black beans","red beans","lotus seeds",
"bok choy","chinese cabbage","napa cabbage","choy sum","gai lan","chinese broccoli","snow peas","water chestnut","bamboo shoots","lotus root",
"shiitake mushroom","wood ear mushroom","enoki mushroom","king oyster mushroom","straw mushroom","eggplant","daikon radish","winter melon","bitter melon","taro",
"rice","jasmine rice","sticky rice","brown rice","rice porridge","congee","rice cake","rice dumpling","noodles","glass noodles",
"egg","duck egg","century egg","salted duck egg","chicken","pork belly","ground pork","beef","lamb","duck",
"shrimp","crab","squid","octopus","fish","carp","tilapia","milk","soy milk","tofu pudding"
]

BARCODE_SEEDS_china = [
"6901234567890","6901234567897","6901234567807","6901234567814","6901234567821",
"6901234567838","6901234567845","6901234567852","6901234567869","6901234567876",
"6911234567893","6911234567890","6911234567886","6911234567879","6911234567862",
"6921234567896","6921234567893","6921234567889","6921234567872","6921234567865",
"6931234567899","6931234567896","6931234567882","6931234567875","6931234567868",
"6941234567892","6941234567899","6941234567885","6941234567878","6941234567861",
"6951234567895","6951234567892","6951234567888","6951234567871","6951234567864",
"6961234567898","6961234567895","6961234567881","6961234567874","6961234567867",
"6971234567891","6971234567898","6971234567884","6971234567877","6971234567860",
"6981234567894","6981234567891","6981234567887","6981234567870","6981234567863",
"6991234567897","6991234567894","6991234567880","6991234567873","6991234567866",
"6909876543210","6909876543217","6909876543224","6909876543231","6909876543248",
"6919876543213","6919876543210","6919876543227","6919876543234","6919876543241",
"6929876543216","6929876543213","6929876543220","6929876543237","6929876543244",
"6939876543219","6939876543216","6939876543223","6939876543230","6939876543247",
"6949876543212","6949876543219","6949876543226","6949876543233","6949876543240",
"6959876543215","6959876543212","6959876543229","6959876543236","6959876543243",
"6969876543218","6969876543215","6969876543222","6969876543239","6969876543246",
"6979876543211","6979876543218","6979876543225","6979876543232","6979876543249",
"6989876543214","6989876543211","6989876543228","6989876543235","6989876543242",
"6999876543217","6999876543214","6999876543221","6999876543238","6999876543245"
]

INGREDIENT_QUERIES_thailand = [
"pad thai","tom yum soup","tom kha soup","green curry","red curry","yellow curry","massaman curry","panang curry","thai fried rice","pineapple fried rice",
"papaya salad","som tam","larb","thai basil chicken","thai basil pork","satay chicken","satay pork","thai omelette","boat noodles","rice noodles",
"egg noodles","glass noodles","sticky rice","jasmine rice","coconut rice","thai rice porridge","rice crackers","spring rolls","thai dumplings","thai sausage",
"fish sauce","oyster sauce","soy sauce","dark soy sauce","sweet chili sauce","chili paste","shrimp paste","tamarind paste","palm sugar","coconut sugar",
"lime juice","rice vinegar","garlic","ginger","galangal","lemongrass","kaffir lime leaves","thai basil","holy basil","cilantro",
"green chili","red chili","bird eye chili","shallots","onion","cabbage","carrot","long beans","bean sprouts","bamboo shoots",
"baby corn","eggplant","thai eggplant","pumpkin","water spinach","morning glory","mushroom","straw mushroom","enoki mushroom","tofu",
"fried tofu","egg","chicken","pork","pork belly","beef","duck","shrimp","squid","crab",
"fish","mackerel","tilapia","anchovies","coconut milk","coconut cream","condensed milk","evaporated milk","milk","yogurt",
"thai iced tea","thai iced coffee","coconut water","sugarcane juice","lime soda","herbal drink","energy drink","fruit juice","mango smoothie","banana smoothie"
]

BARCODE_SEEDS_thailand = [
"8851234567890","8851234567897","8851234567807","8851234567814","8851234567821",
"8851234567838","8851234567845","8851234567852","8851234567869","8851234567876",
"8852234567893","8852234567890","8852234567886","8852234567879","8852234567862",
"8853234567896","8853234567893","8853234567889","8853234567872","8853234567865",
"8854234567899","8854234567896","8854234567882","8854234567875","8854234567868",
"8855234567892","8855234567899","8855234567885","8855234567878","8855234567861",
"8856234567895","8856234567892","8856234567888","8856234567871","8856234567864",
"8857234567898","8857234567895","8857234567881","8857234567874","8857234567867",
"8858234567891","8858234567898","8858234567884","8858234567877","8858234567860",
"8859234567894","8859234567891","8859234567887","8859234567870","8859234567863",
"8850234567897","8850234567894","8850234567880","8850234567873","8850234567866",
"8859876543210","8859876543217","8859876543224","8859876543231","8859876543248",
"8858876543213","8858876543210","8858876543227","8858876543234","8858876543241",
"8857876543216","8857876543213","8857876543220","8857876543237","8857876543244",
"8856876543219","8856876543216","8856876543223","8856876543230","8856876543247",
"8855876543212","8855876543219","8855876543226","8855876543233","8855876543240",
"8854876543215","8854876543212","8854876543229","8854876543236","8854876543243",
"8853876543218","8853876543215","8853876543222","8853876543239","8853876543246",
"8852876543211","8852876543218","8852876543225","8852876543232","8852876543249",
"8851876543214","8851876543211","8851876543228","8851876543235","8851876543242"
]

INGREDIENT_QUERIES_usa = [
"hamburger","cheeseburger","hot dog","fried chicken","grilled chicken","chicken nuggets","buffalo wings","bbq ribs","steak","beef burger",
"turkey sandwich","ham sandwich","club sandwich","grilled cheese sandwich","peanut butter sandwich","jelly sandwich","pizza","pepperoni pizza","cheese pizza","veggie pizza",
"mac and cheese","spaghetti","meatballs","lasagna","alfredo pasta","fettuccine","pancakes","waffles","french toast","bagel",
"croissant","donut","muffin","cupcake","brownie","chocolate chip cookies","oatmeal cookies","ice cream","vanilla ice cream","chocolate ice cream",
"milkshake","chocolate milkshake","strawberry milkshake","apple pie","pumpkin pie","cheesecake","banana bread","cornbread","pretzel","nachos",
"tacos","burritos","quesadilla","salsa","guacamole","scrambled eggs","fried eggs","omelette","bacon","sausage",
"pork chops","ground beef","chicken breast","turkey breast","salmon","tuna","shrimp","crab","lobster","clam chowder",
"mashed potatoes","french fries","sweet potato fries","baked potato","corn on the cob","green beans","broccoli","carrots","salad","caesar salad",
"ranch dressing","ketchup","mustard","mayonnaise","bbq sauce","hot sauce","maple syrup","honey","peanut butter","almond butter",
"milk","chocolate milk","coffee","iced coffee","latte","cappuccino","black tea","green tea","orange juice","apple juice",
"grape juice","lemonade","cola soda","diet soda","root beer","energy drink","sports drink","sparkling water","bottled water","protein shake"
]

BARCODE_SEEDS_usa = [
"0001234567895","0001234567888","0001234567871","0001234567864","0001234567857",
"0001234567840","0001234567833","0001234567826","0001234567819","0001234567802",
"0011234567892","0011234567885","0011234567878","0011234567861","0011234567854",
"0011234567847","0011234567830","0011234567823","0011234567816","0011234567809",
"0021234567899","0021234567882","0021234567875","0021234567868","0021234567851",
"0021234567844","0021234567837","0021234567820","0021234567813","0021234567806",
"0031234567896","0031234567889","0031234567872","0031234567865","0031234567858",
"0031234567841","0031234567834","0031234567827","0031234567810","0031234567803",
"0041234567893","0041234567886","0041234567879","0041234567862","0041234567855",
"0041234567848","0041234567831","0041234567824","0041234567817","0041234567800",
"0051234567890","0051234567883","0051234567876","0051234567869","0051234567852",
"0051234567845","0051234567838","0051234567821","0051234567814","0051234567807",
"0061234567897","0061234567880","0061234567873","0061234567866","0061234567859",
"0061234567842","0061234567835","0061234567828","0061234567811","0061234567804",
"0071234567894","0071234567887","0071234567870","0071234567863","0071234567856",
"0071234567849","0071234567832","0071234567825","0071234567818","0071234567801",
"0081234567891","0081234567884","0081234567877","0081234567860","0081234567853",
"0081234567846","0081234567839","0081234567822","0081234567815","0081234567808",
"0091234567898","0091234567881","0091234567874","0091234567867","0091234567850",
"0091234567843","0091234567836","0091234567829","0091234567812","0091234567805"
]

INGREDIENT_QUERIES = []

BARCODE_SEEDS.extend(BARCODE_SEEDS_WORLD)
BARCODE_SEEDS.extend(BARCODE_SEEDS_KOREAN)
BARCODE_SEEDS.extend(BARCODE_SEEDS_japan)
BARCODE_SEEDS.extend(BARCODE_SEEDS_china)
BARCODE_SEEDS.extend(BARCODE_SEEDS_thailand)
BARCODE_SEEDS.extend(BARCODE_SEEDS_usa)

def _clean_barcode(value: Any) -> Optional[str]:
	digits = re.sub(r"\D", "", str(value or ""))
	# Accept common barcode lengths: UPC-A(12), EAN-13(13), EAN-8(8), ITF-14(14)
	if len(digits) in {8, 12, 13, 14}:
		return digits
	return None


def _extract_barcode_from_result(result: Any) -> Optional[str]:
	if not isinstance(result, dict):
		return None

	for key in ("barcode", "code", "gtinUpc", "gtinUPC", "upc"):
		barcode = _clean_barcode(result.get(key))
		if barcode:
			return barcode

	product = result.get("product")
	if isinstance(product, dict):
		for key in ("upc", "code", "gtinUpc", "barcode"):
			barcode = _clean_barcode(product.get(key))
			if barcode:
				return barcode

	return None


def _is_found(payload: Any) -> bool:
	if payload is None:
		return False
	if isinstance(payload, dict) and "found" in payload:
		return bool(payload.get("found"))
	# Some clients return dicts without a "found" flag on success.
	return isinstance(payload, dict) and len(payload) > 0


def _build_clients() -> Dict[str, Any]:
	avocavo_key = os.getenv("AVOCAVO_NUTRITION_API_KEY", "DEMO_KEY")
	usda_key = os.getenv("USDA_API_KEY", "DEMO_KEY")
	if avocavo_key == "DEMO_KEY":
		logger.warning("AVOCAVO_NUTRITION_API_KEY not found, using DEMO_KEY")
	if usda_key == "DEMO_KEY":
		logger.warning("USDA_API_KEY not found, using DEMO_KEY")

	return {
		"avocavo": AvocavoNutritionClient(api_key=avocavo_key),
		"openfoodfacts": OpenFoodFactsClient(),
		"usda": USDAClient(api_key=usda_key),
	}


def _search_best(client_name: str, client: Any, query: str) -> Any:
	if client_name == "avocavo":
		return client.search_best(query)
	return client.search_best(query, pageSize=5)


def warm_ingredient_caches(
	clients: Dict[str, Any],
	ingredient_queries: List[str],
	sleep_seconds: float,
) -> Set[str]:
	discovered_barcodes: Set[str] = set()

	for idx, query in enumerate(ingredient_queries, start=1):
		logger.info("[%d/%d] search_best ingredient='%s'", idx, len(ingredient_queries), query)

		for client_name, client in clients.items():
			try:
				result = _search_best(client_name, client, query)
				barcode = _extract_barcode_from_result(result)
				if barcode:
					discovered_barcodes.add(barcode)
			except Exception as exc:  # noqa: BLE001
				logger.warning("search_best failed client=%s query='%s' err=%s", client_name, query, exc)

		if sleep_seconds > 0:
			time.sleep(sleep_seconds)

	logger.info("Discovered %d barcode candidates from search_best()", len(discovered_barcodes))
	return discovered_barcodes


def _validate_and_collect_barcodes(
	clients: Dict[str, Any],
	candidates: List[str],
	target_count: int,
	sleep_seconds: float,
) -> List[str]:
	valid_codes: List[str] = []
	seen: Set[str] = set()

	for idx, raw_code in enumerate(candidates, start=1):
		code = _clean_barcode(raw_code)
		if not code or code in seen:
			continue
		seen.add(code)

		found_any = False
		logger.info("[barcode validate %d] code=%s", idx, code)

		for client_name, client in clients.items():
			try:
				payload = client.search_by_barcode(code)
				found = _is_found(payload)
				if found:
					found_any = True
				logger.debug("validate client=%s code=%s found=%s", client_name, code, found)
			except Exception as exc:  # noqa: BLE001
				logger.warning("search_by_barcode failed client=%s code=%s err=%s", client_name, code, exc)

		if found_any:
			valid_codes.append(code)

		if len(valid_codes) >= target_count:
			break

		if sleep_seconds > 0:
			time.sleep(sleep_seconds)

	return valid_codes


def warm_barcode_caches(clients: Dict[str, Any], valid_codes: List[str], sleep_seconds: float) -> None:
	for idx, code in enumerate(valid_codes, start=1):
		logger.info("[%d/%d] warm barcode='%s'", idx, len(valid_codes), code)
		for client_name, client in clients.items():
			try:
				_ = client.search_by_barcode(code)
			except Exception as exc:  # noqa: BLE001
				logger.warning("warm barcode failed client=%s code=%s err=%s", client_name, code, exc)

		if sleep_seconds > 0:
			time.sleep(sleep_seconds)


def save_valid_barcodes(valid_codes: List[str]) -> Path:
	out_dir = APP_ROOT / "data" / "results"
	out_dir.mkdir(parents=True, exist_ok=True)
	out_file = out_dir / "validated_barcodes.json"

	payload = {
		"count": len(valid_codes),
		"barcodes": valid_codes,
	}
	with out_file.open("w", encoding="utf-8") as f:
		json.dump(payload, f, ensure_ascii=False, indent=2)

	return out_file


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Crawl ingredients + barcodes to warm app cache files")
	parser.add_argument("--ingredient-limit", type=int, default=len(INGREDIENT_QUERIES), help="How many ingredient queries to run")
	parser.add_argument("--barcode-target", type=int, default=len(BARCODE_SEEDS), help="Target number of validated barcodes")
	parser.add_argument("--sleep", type=float, default=0.05, help="Sleep seconds between requests")
	return parser.parse_args()


def main() -> None:
	args = parse_args()
	_load_environment()
	ingredient_queries = INGREDIENT_QUERIES[: max(1, args.ingredient_limit)]

	logger.title("CACHE CRAWL START")
	logger.info("Ingredient queries: %d", len(ingredient_queries))
	logger.info("Barcode target: %d", args.barcode_target)

	clients = _build_clients()

	discovered = warm_ingredient_caches(clients, ingredient_queries, args.sleep)

	candidate_pool = list(discovered) + BARCODE_SEEDS
	valid_codes = _validate_and_collect_barcodes(
		clients=clients,
		candidates=candidate_pool,
		target_count=max(1, args.barcode_target),
		sleep_seconds=args.sleep,
	)

	if len(valid_codes) < args.barcode_target:
		logger.warning(
			"Only %d/%d barcodes validated from current candidate pool. "
			"Increase ingredient variety or add more seed barcodes.",
			len(valid_codes),
			args.barcode_target,
		)

	warm_barcode_caches(clients, valid_codes, args.sleep)
	out_file = save_valid_barcodes(valid_codes)

	logger.info("Validated barcodes saved: %s", out_file)
	logger.info("Cache crawl complete. Ingredients=%d, valid_barcodes=%d", len(ingredient_queries), len(valid_codes))
	logger.title("CACHE CRAWL DONE")


if __name__ == "__main__":
	main()
