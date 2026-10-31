"""Lossless aliases where possible; do not infer garment construction from length."""
def canonical_occasion(value):
    return 'Travel' if str(value).strip().lower() == 'vacation' else str(value).strip()

def canonical_occasions(value):
    return ', '.join(dict.fromkeys(canonical_occasion(v) for v in (value or '').split(',') if v.strip()))

def legacy_length(subtype):
    return {'Crop Top':'Cropped','Mini Dress':'Thigh','Midi Dress':'Midi','Maxi Dress':'Maxi'}.get(subtype)

def canonical_pair(category,subtype):
    if subtype == 'Cardigan':return 'Outerwear','Cardigan'
    if subtype == 'Crop Top':return category,None
    if category == 'Dresses' and subtype in {'Mini Dress','Midi Dress','Maxi Dress','Bodycon Dress','Sundress','Gown'}:
        return category,None
    return category,{'Playsuit':'Romper','Matching Set':'Two-piece Set','Co-ord Set':'Two-piece Set','Pumps':'Heels'}.get(subtype,subtype)
