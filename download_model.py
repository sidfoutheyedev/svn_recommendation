# download_model.py
# Run once on every new machine:  python download_model.py
# Saves FashionCLIP into models/fashion-clip, so the job never downloads it again.

from transformers import CLIPModel, CLIPProcessor

from app import config

print("downloading", config.MODEL_NAME, "(about 600 MB)...")
CLIPModel.from_pretrained(config.MODEL_NAME).save_pretrained(config.MODEL_FOLDER)
CLIPProcessor.from_pretrained(config.MODEL_NAME).save_pretrained(config.MODEL_FOLDER)
print("download finished: model is downloaded and saved in", config.MODEL_FOLDER)
