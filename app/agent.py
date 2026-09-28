# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import json
import os
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from dotenv import load_dotenv
from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google import genai
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors.agent_engine_sandbox_code_executor import (
    AgentEngineSandboxCodeExecutor,
)
from google.adk.memory import VertexAiMemoryBankService
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.cloud import firestore, storage
from google.genai import types

from app.a2ui_utils import a2ui_callback

load_dotenv()

# IMPORTANT: Hardcode project ID as a string.
# On Agent Platform, google.auth.default() and GOOGLE_CLOUD_PROJECT return project NUMBER.
# Firestore client requires the project ID string (e.g. qwiklabs-gcp-01-591a05674ea5).
FIRESTORE_PROJECT_ID = "qwiklabs-gcp-01-591a05674ea5"
IMAGES_BUCKET_NAME = "recipe-concierge-images-591a0567"
MEMORY_BANK_ID = "295115517964845056"

DEPLOYMENT_METADATA_PATH = Path(__file__).parent.parent / "deployment_metadata.json"


async def generate_memories_callback(callback_context: CallbackContext):
    try:
        await callback_context.add_session_to_memory()
    except Exception as e:
        print(f"Memory callback notice: {e}")
    return None


def memory_bank_service_builder():
    return VertexAiMemoryBankService(
        project=FIRESTORE_PROJECT_ID,
        location="us-east1",
        agent_engine_id=MEMORY_BANK_ID,
    )


def get_code_executor():
    if DEPLOYMENT_METADATA_PATH.exists():
        with open(DEPLOYMENT_METADATA_PATH, "r") as f:
            meta = json.load(f)
        sandbox_id = meta.get("sandbox_resource_name")
        agent_engine_id = meta.get("remote_agent_runtime_id")
        if sandbox_id:
            return AgentEngineSandboxCodeExecutor(sandbox_resource_name=sandbox_id)
        elif agent_engine_id:
            return AgentEngineSandboxCodeExecutor(agent_engine_resource_name=agent_engine_id)
    return None


code_executor = get_code_executor()


def get_firestore_client():
    return firestore.Client(project=FIRESTORE_PROJECT_ID)


def search_recipes(query: str = "") -> str:
    """Searches for recipes in the Firestore database.

    Args:
        query: Optional search keyword to filter recipes by title or cuisine.

    Returns:
        JSON string listing matching recipes with title, cuisine, and prep time.
    """
    db = get_firestore_client()
    docs = db.collection("recipes").stream()
    results = []
    
    query_lower = query.lower()
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        title = data.get("title", "").lower()
        cuisine = data.get("cuisine", "").lower()
        ingredients = " ".join(data.get("ingredients", [])).lower()
        
        if not query or query_lower in title or query_lower in cuisine or query_lower in ingredients:
            results.append({
                "id": data["id"],
                "title": data.get("title"),
                "cuisine": data.get("cuisine"),
                "prep_time_mins": data.get("prep_time_mins"),
                "ingredients": data.get("ingredients", []),
            })
            
    if not results:
        return f"No recipes found matching query: '{query}'."
    return json.dumps(results, indent=2)


def get_recipe_details(recipe_id: str) -> str:
    """Retrieves full details for a specific recipe by ID.

    Args:
        recipe_id: The document ID of the recipe.

    Returns:
        JSON string containing the recipe title, ingredients, instructions, and prep time.
    """
    db = get_firestore_client()
    doc_ref = db.collection("recipes").document(recipe_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        return f"Recipe with ID '{recipe_id}' not found."
    
    data = doc.to_dict()
    data["id"] = doc.id
    return json.dumps(data, indent=2)


def add_recipe(
    title: str,
    cuisine: str,
    prep_time_mins: int,
    ingredients: str,
    instructions: str,
) -> str:
    """Adds a new recipe to the Firestore database.

    Args:
        title: Title of the recipe.
        cuisine: Cuisine category (e.g., Italian, Mexican, Asian).
        prep_time_mins: Preparation time in minutes.
        ingredients: Comma-separated list of ingredients.
        instructions: Step-by-step preparation instructions.

    Returns:
        Success message with the new recipe document ID.
    """
    db = get_firestore_client()
    doc_id = title.lower().replace(" ", "-").replace("'", "")
    
    ingredient_list = [i.strip() for i in ingredients.split(",") if i.strip()]
    
    recipe_doc = {
        "title": title,
        "cuisine": cuisine,
        "prep_time_mins": prep_time_mins,
        "ingredients": ingredient_list,
        "instructions": instructions,
    }
    
    db.collection("recipes").document(doc_id).set(recipe_doc)
    return f"Successfully added recipe '{title}' with ID '{doc_id}'."


def calculate_recipe_scaling(recipe_id: str, target_servings: int, base_servings: int = 4) -> str:
    """Calculates scaled ingredient quantities for a recipe based on target serving size.

    Args:
        recipe_id: The document ID of the recipe to scale.
        target_servings: Desired number of servings to prepare.
        base_servings: Original recipe base serving size (default: 4).

    Returns:
        JSON string containing the scaled ingredient ratios and serving summary.
    """
    db = get_firestore_client()
    doc_ref = db.collection("recipes").document(recipe_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        return f"Recipe with ID '{recipe_id}' not found."
    
    data = doc.to_dict()
    scale_factor = target_servings / base_servings if base_servings > 0 else 1.0
    
    return json.dumps({
        "recipe_id": recipe_id,
        "title": data.get("title"),
        "base_servings": base_servings,
        "target_servings": target_servings,
        "scale_factor": round(scale_factor, 2),
        "original_ingredients": data.get("ingredients", []),
        "scaling_note": f"Multiply each ingredient quantity by {round(scale_factor, 2)}x for {target_servings} servings."
    }, indent=2)


def fetch_online_recipe_ideas(query: str) -> str:
    """Fetches real-world recipe ideas and inspiration from TheMealDB public API.

    Args:
        query: Name of a dish, ingredient, or cuisine to search for online.

    Returns:
        JSON string listing recipe names, category, area, instructions, and ingredients.
    """
    api_key = os.getenv("THEMEALDB_API_KEY", "1")
    encoded_query = urllib.parse.quote(query)
    url = f"https://www.themealdb.com/api/json/v1/{api_key}/search.php?s={encoded_query}"
    
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "RecipeConciergeAgent/1.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            meals = data.get("meals")
            if not meals:
                return f"No online recipes found matching query: '{query}'."
            
            results = []
            for meal in meals[:3]:
                ingredients = []
                for i in range(1, 21):
                    ing = meal.get(f"strIngredient{i}")
                    meas = meal.get(f"strMeasure{i}")
                    if ing and ing.strip():
                        ingredients.append(f"{meas.strip()} {ing.strip()}".strip() if meas else ing.strip())
                
                results.append({
                    "id": meal.get("idMeal"),
                    "title": meal.get("strMeal"),
                    "category": meal.get("strCategory"),
                    "area": meal.get("strArea"),
                    "instructions": meal.get("strInstructions"),
                    "thumbnail": meal.get("strMealThumb"),
                    "ingredients": ingredients,
                })
            return json.dumps(results, indent=2)
    except Exception as e:
        return f"Error fetching online recipes from API: {str(e)}"


def geocode_address(address: str) -> str:
    """Converts a physical address or landmark into latitude and longitude coordinates using Google Geocoding API.

    Args:
        address: The street address, city, or landmark to geocode (e.g. "1600 Amphitheatre Pkwy, Mountain View, CA").

    Returns:
        JSON string with formatted address and latitude/longitude location coordinates.
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key or api_key == "PASTE_KEY_HERE":
        return "Error: GOOGLE_MAPS_API_KEY is missing or not configured in .env."

    encoded_address = urllib.parse.quote(address)
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={encoded_address}&key={api_key}"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            if data.get("status") != "OK" or not data.get("results"):
                return f"Geocoding failed for '{address}': {data.get('error_message', data.get('status'))}"

            first = data["results"][0]
            location = first["geometry"]["location"]
            return json.dumps({
                "formatted_address": first.get("formatted_address"),
                "location": {
                    "latitude": location.get("lat"),
                    "longitude": location.get("lng"),
                }
            }, indent=2)
    except Exception as e:
        return f"Geocoding request failed: {str(e)}"


def find_nearby_places(
    latitude: float,
    longitude: float,
    place_type: str = "supermarket",
    radius_meters: float = 2000.0,
) -> str:
    """Finds nearby places (e.g. supermarkets, grocery stores, bakeries) near given coordinates using Google Places API (New).

    Args:
        latitude: Center latitude coordinate.
        longitude: Center longitude coordinate.
        place_type: Type of place to search (e.g. "supermarket", "grocery_store", "bakery", "restaurant").
        radius_meters: Search radius in meters (default: 2000.0).

    Returns:
        JSON string listing nearby places with name, formatted address, and location coordinates.
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key or api_key == "PASTE_KEY_HERE":
        return "Error: GOOGLE_MAPS_API_KEY is missing or not configured in .env."

    url = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location",
    }
    body = {
        "includedTypes": [place_type],
        "locationRestriction": {
            "circle": {
                "center": {
                    "latitude": latitude,
                    "longitude": longitude,
                },
                "radius": radius_meters,
            }
        }
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            places = data.get("places", [])
            if not places:
                return f"No nearby '{place_type}' places found within {radius_meters}m."

            results = []
            for p in places[:5]:
                disp_name = p.get("displayName", {})
                name_text = disp_name.get("text") if isinstance(disp_name, dict) else str(disp_name)
                results.append({
                    "name": name_text,
                    "address": p.get("formattedAddress"),
                    "location": p.get("location"),
                })
            return json.dumps(results, indent=2)
    except Exception as e:
        return f"Places API request failed: {str(e)}"


def generate_recipe_image(dish_name: str, tool_context: ToolContext) -> str:
    """Generates an image for a recipe or dish using gemini-3.1-flash-lite-image model in global region.
    Saves the image bytes as an ADK artifact (for Playground panel) and uploads it directly to public Cloud Storage.

    Args:
        dish_name: The name or description of the recipe/dish to generate an image for.
        tool_context: ADK ToolContext injected automatically.

    Returns:
        The public HTTPS URL of the generated image in Cloud Storage.
    """
    client = genai.Client(vertexai=True, project=FIRESTORE_PROJECT_ID, location="global")
    prompt = f"Professional food photography of {dish_name}, delicious presentation, high resolution"

    response = client.models.generate_content(
        model="gemini-3.1-flash-lite-image",
        contents=prompt,
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )

    image_bytes = None
    mime_type = "image/png"
    if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                image_bytes = part.inline_data.data
                if part.inline_data.mime_type:
                    mime_type = part.inline_data.mime_type
                break

    if not image_bytes:
        return f"Failed to generate image for '{dish_name}'."

    filename = f"recipe-{uuid.uuid4().hex[:8]}.png"

    # 1. Save artifact to ADK context (for Playground Artifacts panel)
    artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    tool_context.save_artifact(filename=filename, artifact=artifact_part)

    # 2. Upload image bytes directly to public Cloud Storage bucket
    storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
    bucket = storage_client.bucket(IMAGES_BUCKET_NAME)
    blob = bucket.blob(filename)
    blob.upload_from_string(image_bytes, content_type=mime_type)

    public_url = f"https://storage.googleapis.com/{IMAGES_BUCKET_NAME}/{filename}"
    return public_url


def generate_recipe_video(dish_name: str, tool_context: ToolContext) -> str:
    """Generates a short video for a recipe or culinary item using gemini-omni-flash-preview model in global region.
    Saves the video bytes as an ADK artifact (for Playground panel) and uploads it directly to public Cloud Storage.

    Args:
        dish_name: The name or description of the recipe/dish to generate a short video for.
        tool_context: ADK ToolContext injected automatically.

    Returns:
        The public HTTPS URL of the generated video in Cloud Storage.
    """
    client = genai.Client(vertexai=True, project=FIRESTORE_PROJECT_ID, location="global")
    prompt = f"Short 3 second video showing preparation of {dish_name}, high resolution food presentation"

    video_bytes = None
    mime_type = "video/mp4"

    try:
        interaction = client.interactions.create(
            model="gemini-omni-flash-preview",
            input=prompt,
        )
        if hasattr(interaction, "output_video") and interaction.output_video:
            v = interaction.output_video
            if hasattr(v, "data") and v.data:
                video_bytes = base64.b64decode(v.data) if isinstance(v.data, str) else v.data
                if hasattr(v, "mime_type") and v.mime_type:
                    mime_type = v.mime_type
        elif hasattr(interaction, "outputs") and interaction.outputs:
            for out in interaction.outputs:
                if getattr(out, "mime_type", "").startswith("video/"):
                    d = getattr(out, "data", None) or getattr(out, "bytes", None)
                    if d:
                        video_bytes = base64.b64decode(d) if isinstance(d, str) else d
                        mime_type = out.mime_type
                        break
    except Exception as e:
        return f"Failed to generate video for '{dish_name}': {str(e)}"

    if not video_bytes:
        return f"Failed to extract video bytes for '{dish_name}'."

    filename = f"recipe-video-{uuid.uuid4().hex[:8]}.mp4"

    # 1. Save artifact to ADK context (for Playground Artifacts panel)
    artifact_part = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
    tool_context.save_artifact(filename=filename, artifact=artifact_part)

    # 2. Upload video bytes directly to public Cloud Storage bucket
    storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
    bucket = storage_client.bucket(IMAGES_BUCKET_NAME)
    blob = bucket.blob(filename)
    blob.upload_from_string(video_bytes, content_type=mime_type)

    public_url = f"https://storage.googleapis.com/{IMAGES_BUCKET_NAME}/{filename}"
    return public_url


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

a2ui_instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are Recipe Concierge, a helpful culinary assistant. "
        "You help users search local & online recipes, view detailed instructions, scale recipes for different serving sizes, "
        "add new recipes, geocode locations, find nearby grocery stores or markets, generate recipe dish images, generate recipe dish videos, and execute Python code in a sandbox."
    ),
    workflow_description="Analyze the request and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        "{\"Image\": {\"url\": {\"literalString\": \"https://...\"}}}. Never point an "
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects.\n\n"
        "MEMORY & ALLERGY SAFETY RULES:\n"
        "1. You remember user preferences, dietary restrictions, and allergies across sessions using Memory Bank.\n"
        "2. Whenever a user states an allergy or dietary restriction (e.g. peanuts, gluten, dairy, shellfish, eggs), acknowledge it and store it in Memory Bank.\n"
        "3. ALWAYS check preloaded memories for known user allergies before suggesting recipes, and NEVER recommend a recipe containing ingredients the user is allergic to without warning them."
    ),
    include_schema=True,
    include_examples=True,
)


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-2.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=a2ui_instruction,
    tools=[
        PreloadMemoryTool(),
        search_recipes,
        get_recipe_details,
        add_recipe,
        calculate_recipe_scaling,
        fetch_online_recipe_ideas,
        geocode_address,
        find_nearby_places,
        generate_recipe_image,
        generate_recipe_video,
    ],
    after_agent_callback=generate_memories_callback,
    after_model_callback=a2ui_callback,
    code_executor=code_executor,
)

app = App(
    root_agent=root_agent,
    name="app",
)





