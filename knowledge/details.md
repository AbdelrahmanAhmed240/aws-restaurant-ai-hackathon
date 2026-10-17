----
id: restaurant
type: restaurant
name: Break
language: en
category: restaurant_information
version: 5
last_updated: 2026-10-18

---

# Contact
## Contact: Phone
id: contact_phone
type: contact
name: Delivery and Order Hotline
value: 16099

# Hours
## Hours: Working Hours
id: working_hours
type: hours
name: Working Hours
opens: 10:00
closes: 04:00
note: Daily, seven days a week

# Social Media
## Social Media: Facebook
id: social_facebook
type: social_media
name: Break Restaurant Official Facebook Page
platform: Facebook
url: https://www.facebook.com/RestaurantPage/

# Branches
## Branch: Mohandessin Branch
id: branch_mohandessin
type: branch
name: Mohandessin Branch
category: cairo
address: 45 El Batal Ahmed Abdel Aziz Street, off Gameat El Dowal El Arabiya Street.

## Branch: Mokattam Branch
id: branch_mokattam
type: branch
name: Mokattam Branch
category: cairo
address: Street 9, extension of Fountain Square, next to Etisalat store, in front of Monginis.

## Branch: Sheraton Branch
id: branch_sheraton
type: branch
name: Sheraton Branch
category: cairo
address: 43 Sheraton Housing, First Zone, Ankara Street.

## Branch: Glim Branch
id: branch_glim
type: branch
name: Glim Branch
category: alexandria
aliases:

- Radio Street
address: 30 El-Ezaa Street (Radio Street), Glim.

## Branch: Mandara Branch
id: branch_mandara
type: branch
name: Mandara Branch
category: alexandria
address: El Geish Road, extension of Abdel Halim Mahmoud Mosque Street, in front of Santos Cafe.

## Branch: Camp Caesar Branch
id: branch_camp_caesar
type: branch
name: Camp Caesar Branch
category: alexandria
aliases:

- Camp
address: Camp Caesar, Corniche beachfront, next to Wali Cafeteria.

## Branch: Smouha Branch 1
id: branch_smouha1
type: branch
name: Smouha Branch 1
category: alexandria
address: Smouha Cooperatives, Hatem Mosque Street, behind Security Directorate.

## Branch: Smouha Branch 2
id: branch_smouha2
type: branch
name: Smouha Branch 2
category: alexandria
address: Commercial Market, Hatem Mosque Street.

## Branch: Bahary Branch
id: branch_bahary
type: branch
name: Bahary Branch
category: alexandria
address: 19 26th of July Road, next to El-Saidi Gelato.

## Branch: Sidi Bishr Branch
id: branch_sidi_bishr
type: branch
name: Sidi Bishr Branch
category: alexandria
address: El-Eisawy Street, in front of Electricity Company.

## Branch: Mahrousa Branch
id: branch_mahrousa
type: branch
name: Mahrousa Branch
category: alexandria
address: El Geish Road, right beside El-Mahrousa Tunnel and El-Mahrousa Hotel.

# Delivery
## Delivery: Delivery Policy
id: delivery_policy
type: delivery
name: Delivery Policy
available: true
areas: All areas across Cairo and Alexandria
duration: 30 to 45 minutes
fee: 25 EGP
minimum_order: None

# Payment
## Payment: Delivery Payment
id: payment_delivery
type: payment
name: Payment on Delivery
context: delivery
methods:

- Cash

## Payment: Pickup Payment
id: payment_pickup
type: payment
name: Payment on Pickup
context: pickup
methods:

- Cash
- Visa

# Keywords
## Keywords: Branch Keywords
id: keywords_branches
type: keywords
name: Branch Search Keywords
category: branches
terms:

- branches
- branch
- cairo branches
- alexandria branches
- glim branch
- smouha branch
- mokattam branch
- mohandessin branch
- sheraton branch
- mandara branch
- camp caesar branch
