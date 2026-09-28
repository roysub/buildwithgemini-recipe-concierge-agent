"""Seed script for populating Firestore with sample recipe data."""

from google.cloud import firestore

# IMPORTANT: Hardcode the project ID as a string, DO NOT derive from env or ADC
PROJECT_ID = "qwiklabs-gcp-01-591a05674ea5"

def seed_database():
    db = firestore.Client(project=PROJECT_ID)
    recipes_ref = db.collection("recipes")

    sample_recipes = [
        {
            "id": "tacos-al-pastor",
            "title": "Tacos al Pastor",
            "cuisine": "Mexican",
            "prep_time_mins": 25,
            "ingredients": ["pork", "pineapple", "tortillas", "cilantro", "onion"],
            "instructions": "Marinate pork in achiote and spices, grill with pineapple, serve on warm corn tortillas.",
        },
        {
            "id": "avocado-egg-toast",
            "title": "Avocado & Egg Toast",
            "cuisine": "Breakfast",
            "prep_time_mins": 10,
            "ingredients": ["sourdough bread", "avocado", "eggs", "red pepper flakes", "sea salt"],
            "instructions": "Toast sourdough, mash seasoned avocado on top, finish with a poached egg.",
        },
        {
            "id": "spaghetti-carbonara",
            "title": "Spaghetti Carbonara",
            "cuisine": "Italian",
            "prep_time_mins": 20,
            "ingredients": ["spaghetti", "pancetta", "egg yolks", "pecorino romano", "black pepper"],
            "instructions": "Crisp pancetta, boil pasta al dente, combine with egg yolk & cheese mixture off heat.",
        },
        {
            "id": "thai-green-curry",
            "title": "Thai Green Curry",
            "cuisine": "Thai",
            "prep_time_mins": 30,
            "ingredients": ["chicken breast", "green curry paste", "coconut milk", "bamboo shoots", "thai basil"],
            "instructions": "Simmer curry paste in coconut cream, add chicken and bamboo shoots, garnish with fresh basil.",
        },
    ]

    for item in sample_recipes:
        doc_id = item["id"]
        recipes_ref.document(doc_id).set(item)
        print(f"Seeded recipe: {item['title']} ({doc_id})")

    print("Firestore database seeding completed successfully!")

if __name__ == "__main__":
    seed_database()
