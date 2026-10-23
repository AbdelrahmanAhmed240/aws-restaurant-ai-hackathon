---
id: menu
type: menu
name: Restaurant Menu
language: en
category: menu_knowledge_base
version: 12
last_updated: 2026-10-17
---

# Restaurant Information

## Restaurant Information: Restaurant

id: restaurant_information
type: restaurant
name: Break Restaurant

delivery_available: true
delivery_phone: 16099

## Restaurant Information: Working Hours

id: working_hours
type: hours
name: Working Hours
opens: 10:00
closes: 04:00
note: Daily throughout the week

## Restaurant Information: Branch

id: branch_mohandessin
type: branch
name: Mohandessin
category: cairo
address: 45 Batal Ahmed Abdel Aziz Street, off Gameat El Dowal Al Arabiya Street, Mohandessin, Giza

---

# Meals

## Meal: Quarter Broasted Chicken

id: meal_quarter_broasted_chicken
type: meal
name: Quarter Broasted Chicken
category: chicken

aliases:
- Quarter Chicken
- Quarter Broasted
- Broasted Quarter

price:
  value: 135
  currency: EGP

available: true

ingredients:
- Broasted chicken thigh
- French fries
- Bun
- Small garlic dip
- Ketchup

sauce:
  supports_sauce: false
  free_quantity: 0
  available_count: 0
  available_sauces: []

description:
Quarter Broasted Chicken meal contains:
- Broasted chicken thigh
- French fries
- Fresh bun
- Small garlic dip
- Ketchup

rules:
- Does not include free sauce.
- Does not support sauce selection.

---

## Meal: 3-Piece Chicken Strips Meal

id: meal_strips_3
type: meal
name: 3-Piece Chicken Strips Meal
category: strips

aliases:
- 3 Strips
- Strips 3
- 3 Piece Strips
- Chicken Strips Meal

price:
  value: 150
  currency: EGP

available: true

ingredients:
- Three crispy chicken strips
- French fries
- Bun
- Garlic dip

sauce:
  supports_sauce: false
  free_quantity: 0
  available_count: 0
  available_sauces: []

description:
3-Piece Chicken Strips meal contains:
- Three crispy chicken strips
- French fries
- Fresh bun
- Garlic dip

rules:
- Does not include free sauce.
- Does not support sauce selection.

---

## Meal: 5-Piece Chicken Strips Meal

id: meal_strips_5
type: meal
name: 5-Piece Chicken Strips Meal
category: strips

aliases:
- 5 Strips
- Strips 5
- 5 Piece Strips
- Large Strips Meal

price:
  value: 205
  currency: EGP

available: true

ingredients:
- Five crispy chicken strips
- French fries
- Bun
- Garlic dip

sauce:
  supports_sauce: false
  free_quantity: 0
  available_count: 0
  available_sauces: []

description:
5-Piece Chicken Strips meal contains:
- Five crispy chicken strips
- French fries
- Fresh bun
- Garlic dip

rules:
- Does not include free sauce.
- Does not support sauce selection.

---

## Meal: Break Meal

id: meal_albaraka
type: meal
name: Break Meal
category: chicken

aliases:
- Break
- Half Chicken
- Half Broasted Chicken

price:
  value: 235
  currency: EGP

available: true

ingredients:
- Half broasted chicken
- French fries
- Bun
- Garlic dip
- Coleslaw
- Ketchup

sauce:
  supports_sauce: false
  free_quantity: 0
  available_count: 0
  available_sauces: []

description:
Break Meal contains:
- Half broasted chicken
- French fries
- Fresh bun
- Garlic dip
- Coleslaw salad
- Ketchup

rules:
- Does not include free sauce.
- Does not support sauce selection.

---

## Meal: Crispy Chicken Fatta

id: meal_fatta
type: meal
name: Crispy Chicken Fatta
category: rice

aliases:
- Fatta
- Chicken Fatta
- Fatta Meal

price:
  value: 160
  currency: EGP

available: true

ingredients:
- Basmati rice
- Chicken strips
- Coleslaw
- Toasted bread

sauce:
  supports_sauce: true
  free_quantity: 1
  available_count: 5
  available_sauces:
  - BBQ
  - Garlic Dip
  - Ranch
  - Sweet Chili
  - Cheddar Cheese

description:
Crispy Chicken Fatta contains:
- Seasoned basmati rice
- Crispy chicken strips
- Coleslaw salad
- Crispy toasted bread

rules:
- Includes choice of 1 free sauce.
- Customer may choose exactly 1 sauce.
- Available sauces count: 5.

---

## Meal: Basmatio Rice Meal

id: meal_basmatio
type: meal
name: Basmatio Rice Meal
category: rice

aliases:
- Basmatio
- Basmati Meal
- Rice with Strips

price:
  value: 105
  currency: EGP

available: true

ingredients:
- Basmati rice
- Chicken strips
- Coleslaw

sauce:
  supports_sauce: true
  free_quantity: 1
  available_count: 5
  available_sauces:
  - BBQ
  - Garlic Dip
  - Ranch
  - Sweet Chili
  - Cheddar Cheese

description:
Basmatio Rice Meal contains:
- Seasoned basmati rice
- Crispy chicken strips pieces
- Coleslaw salad

rules:
- Includes choice of 1 free sauce.
- Customer may choose exactly 1 sauce.
- Available sauces count: 5.

---

# Add-ons

## Add-on: Extra Chicken Strip

id: addon_strip
type: addon
name: Extra Chicken Strip

aliases:
- Extra Strip
- Chicken Strip
- 1 Strip Piece

price:
  value: 35
  currency: EGP

available: true

description:
One additional piece of crispy fried chicken strip.

---

## Add-on: Basmati Rice

id: addon_basmati
type: addon
name: Basmati Rice

aliases:
- Rice
- Yellow Rice
- Extra Rice

price:
  value: 25
  currency: EGP

available: true

description:
Side portion of seasoned yellow basmati rice.

---

## Add-on: French Fries

id: addon_fries
type: addon
name: French Fries

aliases:
- Fries
- Packet of Fries
- Extra Fries

price:
  value: 35
  currency: EGP

available: true

description:
Crispy golden potato French fries packet.

---

## Add-on: Large Garlic Dip

id: addon_garlic
type: addon
name: Large Garlic Dip

aliases:
- Large Garlic
- Extra Garlic
- Large Toumaya

price:
  value: 15
  currency: EGP

available: true

description:
Large creamy garlic sauce dip.

---

## Add-on: Kaiser Bun

id: addon_kaiser
type: addon
name: Kaiser Bun

aliases:
- Bun
- Bread
- Extra Bun

price:
  value: 5
  currency: EGP

available: true

description:
Fresh restaurant burger bun.

---

## Add-on: Coleslaw

id: addon_coleslaw
type: addon
name: Coleslaw

aliases:
- Coleslaw Salad
- Extra Coleslaw
- Salad

price:
  value: 15
  currency: EGP

available: true

description:
Fresh cabbage and carrot coleslaw salad.

---

# Sauces

## Sauce: BBQ Sauce

id: sauce_bbq
type: sauce
name: BBQ Sauce

aliases:
- BBQ
- Barbecue
- Barbecue Sauce

price:
  value: 25
  currency: EGP

available: true

description:
Smoky barbecue dipping sauce.

---

## Sauce: Cheddar Cheese Sauce

id: sauce_cheddar
type: sauce
name: Cheddar Cheese Sauce

aliases:
- Cheddar
- Cheese Sauce
- Cheesy Sauce

price:
  value: 35
  currency: EGP

available: true

description:
Rich melted cheddar cheese dipping sauce.

---

## Sauce: Ranch Sauce

id: sauce_ranch
type: sauce
name: Ranch Sauce

aliases:
- Ranch
- Ranch Dip

price:
  value: 15
  currency: EGP

available: true

description:
Herb and buttermilk ranch dipping sauce.

---

## Sauce: Sweet Chili Sauce

id: sauce_sweet_chili
type: sauce
name: Sweet Chili Sauce

aliases:
- Sweet Chili
- Sweet Chilli
- Sweet Chili Dip

price:
  value: 15
  currency: EGP

available: true

description:
Sweet and spicy dipping sauce.

---

## Sauce: Garlic Dip

id: sauce_garlic
type: sauce
name: Garlic Dip

aliases:
- Garlic
- Toumaya
- Garlic Sauce

price:
  value: 15
  currency: EGP

available: true

description:
Traditional creamy garlic dip.

---

# Drinks

## Drink: Soft Drink

id: drink_soft
type: drink
name: Soft Drink

aliases:
- Pepsi
- Soda
- Can
- 7Up
- Mirinda

price:
  value: 25
  currency: EGP

available: true

description:
Cold carbonated soft drink (Pepsi, 7Up, or Mirinda).

---

## Drink: Mineral Water

id: drink_water
type: drink
name: Mineral Water

aliases:
- Water
- Water Bottle
- Bottled Water

price:
  value: 10
  currency: EGP

available: true

description:
500ml bottle of pure mineral drinking water.

---

# Extras

## Extra: Ribbon Fries

id: extra_strip_fries
type: extra
name: Ribbon Fries

aliases:
- Ribbon Fries
- Spiral Fries
- Curly Fries

price:
  value: 25
  currency: EGP

available: true

description:
Seasoned spiral ribbon cut potato fries.

---

# Combo Upgrade

## Combo: Combo Upgrade

id: combo_upgrade
type: combo_upgrade
name: Combo Upgrade

aliases:
- Combo
- Upgrade to Combo
- Make it Combo

price:
  value: 50
  currency: EGP

available: true

includes:
- French Fries
- Soft Drink

description:
Any meal can be upgraded to a combo with French fries and a soft drink.

rules:
- Combo upgrade is available with Meals.
- Includes a packet of French fries and a soft drink.

---

# Restaurant Rules

## Sauce Rules

id: sauce_rules
type: rules
name: Sauce Rules

description:
Only these meals support free sauce:
- Crispy Chicken Fatta:
  - free_sauce_quantity: 1
- Basmatio Rice Meal:
  - free_sauce_quantity: 1

All other meals:
- Do not support free sauce selection.
- Sauces may be ordered as add-ons.

---

# Sauce Availability

## Sauce Availability: Available Sauces

id: sauce_availability
type: sauce_availability
name: Available Sauces

description:
Available sauces:
- BBQ Sauce
- Garlic Dip
- Ranch Sauce
- Sweet Chili Sauce
- Cheddar Cheese Sauce

Sauce prices:
- BBQ Sauce: 25 EGP
- Cheddar Cheese Sauce: 35 EGP
- Ranch Sauce: 15 EGP
- Sweet Chili Sauce: 15 EGP
- Garlic Dip: 15 EGP

---

# Menu Categories

## Menu Categories: Categories

id: menu_categories
type: menu_categories
name: Menu Categories

categories:
- 🍗 Meals
- ➕ Add-ons
- 🥫 Sauces
- 🥤 Drinks
- 🍟 Extras
- ⭐ Combo Upgrade

---

# Search Keywords

## Search Keywords: Meals

id: search_keywords_meals
type: keywords
name: Search Keywords Meals
category: meals

terms:
- Quarter Broasted Chicken
- Broasted
- 3-Piece Chicken Strips Meal
- 5-Piece Chicken Strips Meal
- Strips
- Break Meal
- Break
- Crispy Chicken Fatta
- Fatta
- Basmatio Rice Meal
- Basmatio

---

# Retrieval Notes

## Retrieval Notes: Meal Sauce Lookup

id: retrieval_notes_sauce_lookup
type: retrieval_notes
name: Meal Sauce Lookup Notes

description:
When a customer asks about sauces for a meal:
1. Identify the exact meal.
2. Use only that meal's sauce fields.
3. Crispy Chicken Fatta and Basmatio Rice Meal each include 1 free sauce choice.
4. All other meals do not include free sauces.

fields:
- supports_sauce
- free_sauce_quantity
- available_sauces

---

# Response Rules

## Response Rules: Unknown Information

id: response_rules_unknown
type: response_rules
name: Response Rules - Unknown Information

description:
If information is unavailable or not present in restaurant knowledge, politely reply:
I am sorry, this information is not available in our restaurant knowledge base.

---

## Response Rules: Recommendations

id: response_rules_recommendations
type: response_rules
name: Response Rules - Recommendations

description:
When customers ask for recommendations, suggest popular available meals:
- Break Meal (Half broasted chicken with French fries, fresh bun, garlic dip, coleslaw salad, and ketchup) for 235 EGP
- 3-Piece Chicken Strips Meal for 150 EGP
- Crispy Chicken Fatta for 160 EGP
- Basmatio Rice Meal for 105 EGP
Always state exact prices in EGP and mention optional combo upgrades (+50 EGP for fries and a drink).

---

# Knowledge Source

## Knowledge Source: Menu

id: knowledge_source_menu
type: knowledge_source
name: Menu Knowledge Source

description:
All information in this file belongs to Break Restaurant authoritative menu information.
Only use the verified restaurant catalog when answering customer questions.
