from src.categories.index import find_category_by_query, store

store.load()
print("Categories loaded:", store.categories.keys())

queries = [
    "спадщина",
    "кастомний договір",
    "оренда квартири",
    "створити свій",
    "договір дарування"
]

for q in queries:
    cat = find_category_by_query(q)
    print(f"Query: '{q}' -> Category: {cat.id if cat else 'None'}")
