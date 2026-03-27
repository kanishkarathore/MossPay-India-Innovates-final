from geopy.distance import geodesic
# Assuming lca_service.py is in the same folder
# For now, we'll mock the LCA call directly in the engine to keep it simple, 
# or you can paste the lca_service.py we made earlier into this folder!

class CarbonEngine:
    def __init__(self):
        # Emission factors for the new Packaging variable (kg CO2e per kg of product)
        self.packaging_factors = {
            "jute": 0.02,
            "cardboard": 0.08,
            "plastic_single_use": 0.25,
            "none": 0.00
        }

    def calculate_batch_emission(self, transaction_data):
        """
        Calculates the carbon footprint of a newly split batch.
        transaction_data requires: 
        - product_root_name (from NLP)
        - quantity_kg
        - origin_coords, dest_coords
        - shelf_life_days
        - packaging_type
        - inherited_co2e (from parent batch)
        """
        print(f"\n--- [CARBON ENGINE] Processing Batch Split ---")
        
        # 1. Inherited Carbon (The Parent-Child Math)
        # If the parent batch had 50kg CO2e, and we bought 50%, we inherit that proportion.
        # For simplicity in this function, we assume the 'inherited_co2e' passed in 
        # is already proportionally calculated by the app.py before sending.
        inherited_carbon = transaction_data.get('inherited_co2e', 0.0)
        print(f"[ENGINE] Inherited from Parent: {inherited_carbon} kg CO2e")

        # 2. Manufacturing / Gov LCA Base (Only applies if this is the FIRST time the item is created)
        # If it's moving vendor-to-vendor, the LCA is already in the 'inherited_carbon'.
        lca_base = 0.0
        if inherited_carbon == 0.0: # Meaning this is Farmer A adding a brand new crop
            print(f"[ENGINE] Fetching Gov LCA for brand new crop: {transaction_data['product_root_name']}")
            lca_base = 0.55 * transaction_data['quantity_kg'] # Mocking the Gov API return for demo

        # 3. Transport Logic (Geopy)
        distance_km = geodesic(
            transaction_data['origin_coords'], 
            transaction_data['dest_coords']
        ).km
        transport_impact = distance_km * 0.0001 * transaction_data['quantity_kg']
        print(f"[ENGINE] Transport ({round(distance_km,1)}km): {round(transport_impact, 4)} kg CO2e")

        # 4. Shelf Life
        storage_impact = transaction_data.get('shelf_life_days', 1) * 0.05 * transaction_data['quantity_kg']
        
        # 5. The New Factor: Packaging
        pack_type = transaction_data.get('packaging_type', 'none').lower()
        pack_factor = self.packaging_factors.get(pack_type, 0.0)
        packaging_impact = pack_factor * transaction_data['quantity_kg']
        print(f"[ENGINE] Packaging ({pack_type}): {round(packaging_impact, 4)} kg CO2e")

        # TOTAL MATH
        total_new_emission = lca_base + transport_impact + storage_impact + packaging_impact
        final_batch_total = inherited_carbon + total_new_emission

        print(f"[ENGINE] Total Footprint for new Batch: {round(final_batch_total, 4)} kg CO2e\n")

        return {
            "final_total": round(final_batch_total, 4),
            "breakdown": {
                "inherited": inherited_carbon,
                "lca_base": lca_base,
                "transport": round(transport_impact, 4),
                "storage": round(storage_impact, 4),
                "packaging": round(packaging_impact, 4)
            }
        }