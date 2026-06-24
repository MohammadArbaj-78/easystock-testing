"""
Generic Substitute Database
============================
Yeh file branded dawaiyon ke saath unke saalt/composition aur
sasti generic alternatives ka starter data rakhti hai.

Naya entry add karna ho to neeche SUBSTITUTE_DATA list mein
ek naya dictionary jod dein, isi format mein:

{
    "brand": "Brand Ka Naam",
    "salt": "Composition/Saalt",
    "generic_alternatives": ["Generic Naam 1", "Generic Naam 2"],
    "category": "Dawai ki category"
}
"""

SUBSTITUTE_DATA = [
    {"brand": "Crocin", "salt": "Paracetamol 500mg", "generic_alternatives": ["Paracip 500", "Dolo 650", "Calpol"], "category": "Pain/Fever"},
    {"brand": "Combiflam", "salt": "Ibuprofen + Paracetamol", "generic_alternatives": ["Flexon", "Ibugesic Plus"], "category": "Pain/Fever"},
    {"brand": "Saridon", "salt": "Paracetamol + Caffeine", "generic_alternatives": ["Pacimol Plus"], "category": "Pain/Fever"},
    {"brand": "Disprin", "salt": "Aspirin 350mg", "generic_alternatives": ["Ecosprin"], "category": "Pain/Fever"},
    {"brand": "Augmentin 625", "salt": "Amoxicillin + Clavulanic Acid", "generic_alternatives": ["Moxikind-CV 625", "Clavam 625"], "category": "Antibiotic"},
    {"brand": "Azithral 500", "salt": "Azithromycin 500mg", "generic_alternatives": ["Azee 500", "Zithrocin 500"], "category": "Antibiotic"},
    {"brand": "Cifran 500", "salt": "Ciprofloxacin 500mg", "generic_alternatives": ["Ciplox 500", "Cipro"], "category": "Antibiotic"},
    {"brand": "Taxim-O", "salt": "Cefixime 200mg", "generic_alternatives": ["Zifi 200", "Cefix 200"], "category": "Antibiotic"},
    {"brand": "Norflox-TZ", "salt": "Norfloxacin + Tinidazole", "generic_alternatives": ["Nortaz", "Zanocin-OZ"], "category": "Antibiotic"},
    {"brand": "Pan 40", "salt": "Pantoprazole 40mg", "generic_alternatives": ["Pantocid 40", "Pantop 40"], "category": "Acidity/Gas"},
    {"brand": "Pan-D", "salt": "Pantoprazole + Domperidone", "generic_alternatives": ["Pantocid-DSR", "Pantodac-DSR"], "category": "Acidity/Gas"},
    {"brand": "Rantac 150", "salt": "Ranitidine 150mg", "generic_alternatives": ["Aciloc 150", "Zinetac 150"], "category": "Acidity/Gas"},
    {"brand": "Digene", "salt": "Antacid (Magaldrate)", "generic_alternatives": ["Mucaine Gel", "Gelusil"], "category": "Acidity/Gas"},
    {"brand": "Eldoper", "salt": "Loperamide 2mg", "generic_alternatives": ["Lopamide", "Imodium"], "category": "Diarrhea"},
    {"brand": "Electral", "salt": "ORS Powder", "generic_alternatives": ["Enerzal", "ORSL"], "category": "Diarrhea/Dehydration"},
    {"brand": "Avil 25", "salt": "Pheniramine Maleate", "generic_alternatives": ["Phenergan"], "category": "Allergy"},
    {"brand": "Allegra 120", "salt": "Fexofenadine 120mg", "generic_alternatives": ["Fexova 120", "Fexoplast"], "category": "Allergy"},
    {"brand": "Cetrizine (Alerid)", "salt": "Cetirizine 10mg", "generic_alternatives": ["Cetzine", "Okacet"], "category": "Allergy"},
    {"brand": "Montair-LC", "salt": "Montelukast + Levocetirizine", "generic_alternatives": ["Montek-LC", "Asthakind-LC"], "category": "Allergy/Cold"},
    {"brand": "Sinarest", "salt": "Paracetamol + Phenylephrine + Cetirizine", "generic_alternatives": ["Cold-D", "D-Cold Total"], "category": "Cold/Cough"},
    {"brand": "Benadryl", "salt": "Diphenhydramine + Ammonium Chloride", "generic_alternatives": ["Phensedyl", "Tixylix"], "category": "Cold/Cough"},
    {"brand": "Ascoril", "salt": "Bromhexine + Salbutamol + Guaifenesin", "generic_alternatives": ["Grilinctus", "Alex"], "category": "Cold/Cough"},
    {"brand": "Vicks Action 500", "salt": "Paracetamol + Phenylephrine + Caffeine", "generic_alternatives": ["Cheston Cold"], "category": "Cold/Cough"},
    {"brand": "Metrogyl 400", "salt": "Metronidazole 400mg", "generic_alternatives": ["Flagyl 400", "Aristogyl 400"], "category": "Infection"},
    {"brand": "Calpol", "salt": "Paracetamol Syrup", "generic_alternatives": ["Crocin Syrup", "Febrex"], "category": "Pediatric"},
    {"brand": "Zincovit", "salt": "Multivitamin + Zinc", "generic_alternatives": ["Supradyn", "Becosules Z"], "category": "Vitamins/Supplements"},
    {"brand": "Shelcal 500", "salt": "Calcium + Vitamin D3", "generic_alternatives": ["Calcimax", "Calcirol"], "category": "Vitamins/Supplements"},
    {"brand": "Neurobion Forte", "salt": "Vitamin B Complex", "generic_alternatives": ["Cobadex CZS", "Maxirich"], "category": "Vitamins/Supplements"},
    {"brand": "Liv 52", "salt": "Herbal Liver Tonic", "generic_alternatives": ["Livogen", "Hepamerz"], "category": "Liver/Tonic"},
    {"brand": "Metformin (Glycomet)", "salt": "Metformin 500mg", "generic_alternatives": ["Glucophage", "Obimet"], "category": "Diabetes"},
    {"brand": "Telma 40", "salt": "Telmisartan 40mg", "generic_alternatives": ["Telsartan 40", "Cresar 40"], "category": "Blood Pressure"},
    {"brand": "Amlokind 5", "salt": "Amlodipine 5mg", "generic_alternatives": ["Amlopres 5", "Amlovas 5"], "category": "Blood Pressure"},
    {"brand": "Ecosprin AV", "salt": "Aspirin + Atorvastatin", "generic_alternatives": ["Aztor-A", "Storvas-AV"], "category": "Heart"},
    {"brand": "Volini Gel", "salt": "Diclofenac Topical Gel", "generic_alternatives": ["Moov", "Iodex Gel"], "category": "Pain Relief (Topical)"},
    {"brand": "Flexon Gel", "salt": "Ibuprofen Gel", "generic_alternatives": ["Voveran Gel"], "category": "Pain Relief (Topical)"},
    {"brand": "Betadine", "salt": "Povidone Iodine", "generic_alternatives": ["Cipladine", "Wokadine"], "category": "Antiseptic"},
    {"brand": "Soframycin", "salt": "Framycetin Skin Cream", "generic_alternatives": ["Soframycin Generic", "Framygen"], "category": "Skin/Antiseptic"},
    {"brand": "Candid-B", "salt": "Clotrimazole + Beclomethasone", "generic_alternatives": ["Tenovate-GM", "Quadriderm"], "category": "Skin/Fungal"},
    {"brand": "Itraspan 100", "salt": "Itraconazole 100mg", "generic_alternatives": ["Candiforce 100", "Itrabest"], "category": "Skin/Fungal"},
    {"brand": "Susten 200", "salt": "Progesterone 200mg", "generic_alternatives": ["Gestone", "Progyluton"], "category": "Women's Health"},
    {"brand": "Meftal Spas", "salt": "Mefenamic Acid + Dicyclomine", "generic_alternatives": ["Cyclopam", "Spasmonil"], "category": "Pain (Stomach/Period)"},
    {"brand": "Drotin", "salt": "Drotaverine 80mg", "generic_alternatives": ["Spasmo Proxyvon", "No Spasm"], "category": "Pain (Stomach)"},
    {"brand": "Ondem 4", "salt": "Ondansetron 4mg", "generic_alternatives": ["Emeset 4", "Vomikind 4"], "category": "Nausea/Vomiting"},
    {"brand": "Domstal", "salt": "Domperidone 10mg", "generic_alternatives": ["Vomistop", "Dompy"], "category": "Nausea/Vomiting"},
    {"brand": "Wikoryl", "salt": "Paracetamol + Phenylephrine + Chlorpheniramine", "generic_alternatives": ["Coldact", "Cetapin Cold"], "category": "Cold/Cough"},
    {"brand": "Ketorol-DT", "salt": "Ketorolac 10mg", "generic_alternatives": ["Toraday", "Ketanov"], "category": "Pain Relief"},
    {"brand": "Nise 100", "salt": "Nimesulide 100mg", "generic_alternatives": ["Nimulid", "Nimesulide Generic"], "category": "Pain Relief"},
    {"brand": "Vertin 16", "salt": "Betahistine 16mg", "generic_alternatives": ["Vertigon", "Betavert"], "category": "Vertigo/Dizziness"},
    {"brand": "Stamlo 5", "salt": "Amlodipine 5mg", "generic_alternatives": ["Amlokind 5", "Amlopres 5"], "category": "Blood Pressure"},
]
