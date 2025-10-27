import google.generativeai as genai

# Configure your API key
genai.configure(api_key='AIzaSyBlqNgRSeCnzmNQ6VU5M6pENUvSmynBzOs')

# List all models and filter for those that support content generation
print("Available Gemini Models (as of Oct 2025):\n")
for model in genai.list_models():
    if 'generateContent' in model.supported_generation_methods:  # Focus on text/image gen models
        print(f"- Name: {model.name}")
        print(f"  Display Name: {model.display_name}")
        print(f"  Description: {model.description}")
        print(f"  Supported Generation Methods: {model.supported_generation_methods}")
        print("---")
