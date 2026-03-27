import spacy
from thefuzz import process

class NLPStandardizer:
    def __init__(self):
        try:
            self.nlp = spacy.load("en_core_web_sm")
        except OSError:
            print("[ERROR] spaCy model not found. Run: python -m spacy download en_core_web_sm")
            self.nlp = None

        self.lca_master_list = [
            "rice", "wheat", "apple", "tomato", "potato", "cotton", "onion", 
            "mango", "banana", "milk", "cheese", "chicken", "beef", "corn", 
            "soybean", "sugar", "coffee", "tea", "lentils", "peas", "garlic", "ginger"
        ]

        self.regional_knowledge = {
            "chawal": "rice", "dhan": "rice", "basmati": "rice",
            "gehu": "wheat", "atta": "wheat", "maida": "wheat",
            "seb": "apple", 
            "tamatar": "tomato", 
            "aloo": "potato", 
            "pyaz": "onion", "kanda": "onion",
            "aam": "mango", 
            "kela": "banana", 
            "dudh": "milk", 
            "murghi": "chicken", 
            "makka": "corn", "bhutta": "corn",
            "chini": "sugar", "gud": "sugar",
            "chai": "tea", "patti": "tea",
            "dal": "lentils", "masoor": "lentils", "moong": "lentils",
            "lahsun": "garlic", 
            "adrak": "ginger",
            "kapas": "cotton", "rui": "cotton"
        }

    def standardize(self, user_input):
        print(f"\n--- [NLP PIPELINE] Analyzing: '{user_input}' ---")
        clean_input = str(user_input).strip().lower()

        # 1. Regional Check
        if clean_input in self.regional_knowledge:
            root = self.regional_knowledge[clean_input]
            print(f"  ↳ [Regional Map] Translated '{clean_input}' -> '{root.title()}'")
            return root

        # 2. Fuzzy Typo Check
        best_match, score = process.extractOne(clean_input, self.lca_master_list)
        if score >= 85:
            print(f"  ↳ [Fuzzy Match] Corrected to -> '{best_match}' (Confidence: {score}%)")
            return best_match

        # 3. True NLP (Lemmatization)
        if self.nlp:
            doc = self.nlp(clean_input)
            for token in doc:
                if token.pos_ in ["NOUN", "PROPN"]:
                    if token.lemma_ in self.lca_master_list:
                        print(f"  ↳ [ML Lemmatization] Extracted -> '{token.lemma_}'")
                        return token.lemma_
                    else:
                        # SILENT FALLBACK 1: Passes valid noun without a warning message
                        return token.lemma_

        # 4. Ultimate Fallback 
        # SILENT FALLBACK 2: Passes original text without a warning message
        return clean_input