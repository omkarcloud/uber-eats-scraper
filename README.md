# 🍔 Uber Eats Scraper

Uber Eats Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Uber Eats data for free.

## ✨ What Can I Get?

- 🍔 **Full store details in 35 countries** — phone, address, coordinates, hours, rating, cuisines & chain
- 📋 **Complete menus** — every item with price, photo, popularity & all customization options
- 🔎 **80 stores per search** — any address, with rating, price, delivery-time & offer filters
- 🗺️ **The whole directory** — every city, neighborhood and brand location Uber Eats lists

## 🍟 Example: A Full Uber Eats Store

```json
{
  "id": "65686398-f585-439b-ae4c-dabe058a0a60",
  "name": "Five Guys (253 W. 42nd St.) NY - 1499",
  "link": "https://www.ubereats.com/store/five-guys-253-w-42nd-st-ny-1499/ZWhjmPWFQ5uuTNq-BYoKYA",
  "phone": "+12123982600",
  "merchant_type": "restaurant",
  "price_range": "$",
  "cuisines": ["American", "Burgers", "Hot Dog", "Family Meals", "Sandwich", "Fast Food", "Snacks"],
  "rating": 4.6,
  "review_count": 8000,
  "is_open": true,
  "status": "Open until 3:53 AM",
  "currency": "USD",
  "location": {
    "address": "253 W 42nd St, New York, NY 10036",
    "city": "New York",
    "region": "NY",
    "postal_code": "10036",
    "country": "US",
    "latitude": 40.7569903,
    "longitude": -73.9896063
  },
  "delivery": {
    "min_minutes": 11,
    "max_minutes": 23,
    "distance": { "value": 0.2, "unit": "mi" },
    "is_within_range": true
  },
  "hours": [
    {
      "days": "Every Day",
      "periods": [
        { "menu": "Menu", "opens_at": "06:30", "closes_at": "03:53", "closes_next_day": true }
      ]
    }
  ],
  "chain": { "id": "a32f0de2-ec42-44ee-965b-7b420b86e9f8", "name": "Five Guys" },
  "menus": [
    { "id": "a7abc1e5-7f23-5a76-ae26-32b76268deec", "title": "Menu", "hours_text": "6:30 AM – 3:53 AM", "item_count": 41 }
  ],
  "joined_at": "2020-02-04T01:22:17Z"
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Uber Eats Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/uber-eats-scraper
cd uber-eats-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/stores/details?store=ZWhjmPWFQ5uuTNq-BYoKYA"
```

```json
{
  "location": null,
  "store": {
    "id": "65686398-f585-439b-ae4c-dabe058a0a60",
    "name": "Five Guys (253 W. 42nd St.) NY - 1499",
    "link": "https://www.ubereats.com/store/five-guys-253-w-42nd-st-ny-1499/ZWhjmPWFQ5uuTNq-BYoKYA",
    "phone": "+12123982600",
    "price_range": "$",
    "cuisines": ["American", "Burgers", "Hot Dog", "Family Meals", "Sandwich", "Fast Food", "Snacks"],
    "rating": 4.6,
    "review_count": 8000,
    "is_open": true,
    "status": "Open until 12:53 AM",
    "currency": "USD",
    "location": {
      "address": "253 W 42nd St, New York, NY 10036",
      "latitude": 40.7569903,
      "longitude": -73.9896063
    },
    "chain": { "id": "a32f0de2-ec42-44ee-965b-7b420b86e9f8", "name": "Five Guys" }
  }
}
```

All 20 endpoints are now live at `http://localhost:8000`.

Seeing `403` after a few hundred store or search calls? Uber Eats puts a reCAPTCHA wall in front of a busy IP. Set `UBER_EATS_PROXY=http://user:pass@host:port` (a residential proxy) before `python run.py` and keep going.

## 📚 Endpoints

20 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Store Details | `/stores/details` | Phone, address, hours, rating and delivery estimate in one call |
| Store Menu | `/stores/menu` | Every menu item with price, photo and popularity |
| Menu Item Details | `/stores/menu/item` | Every size, topping and side with its price |
| Store Reviews | `/stores/reviews` | Customer reviews with names and dates |
| Address Autocomplete | `/locations/autocomplete` | Address suggestions as you type |
| Resolve Location | `/locations/details` | Any address turned into a clean delivery point |
| Search Stores | `/stores/search` | 80 stores per page for any dish or cuisine, filterable |
| Nearby Stores | `/stores/nearby` | Every store delivering to an address, filterable |
| Store Collections | `/stores/collections` | The home feed shelves: favorites, offers, popular |
| Search Store Menu | `/stores/menu/search` | Find any dish or product inside one store |
| Menu Section | `/stores/menu/section` | A full grocery aisle or menu section, paged |
| Search Suggestions | `/search/suggestions` | Search-box completions and matching stores |
| Popular Searches | `/search/popular` | Top cuisines and top grocery searches at an address |
| City Stores | `/cities/stores` | A city's stores, 20 per page, by cuisine if you like |
| City Details | `/cities/details` | A city's top cuisines, FAQ and nearby cities |
| Cities | `/cities` | Every city served in a country, grouped by state |
| Countries | `/countries` | Every country Uber Eats operates in |
| Neighborhood Stores | `/neighborhoods/stores` | Up to 80 stores of one neighborhood |
| Brand Stores | `/brands/stores` | Every location of a chain in a city, with coordinates |
| Brand Details | `/brands/details` | Every city a chain delivers in, with location counts |


## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-uber-eats-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-uber-eats-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-uber-eats-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/stores/search",
    params={"query": "sushi", "location": "Times Square, New York"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Uber Eats Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Uber%20Eats%20Scraper%20API.)

[![Ask Us by Email about Uber Eats Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Uber%20Eats%20Scraper%20API&body=I%20need%20help%20using%20the%20Uber%20Eats%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**Yelp Scraper**](https://www.omkar.cloud/tools/yelp-scraper) — Yelp businesses: ratings, reviews, hours, photos & menus
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/uber-eats-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/uber-eats-scraper)
