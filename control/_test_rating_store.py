# test_rating_store.py

from launch_rating import rating_store



print(f"base_dir    -> {rating_store.base_dir}")
print(f"ratings_dir -> {rating_store.ratings_dir}")
print(f"file        -> {rating_store.file}")

# test write
rating_store.record_success("TestApp", "path")
rating_store.record_success("TestApp", "path")
rating_store.record_success("TestApp", "exe")

# test read
data = rating_store.load()
print(f"data        -> {data}")

# test reorder
attempts = [
    {"method": "exe",   "path": "test.exe"},
    {"method": "path",  "path": "C:\\test.exe"},
    {"method": "shell", "path": "C:\\test.exe"},
]
reordered = rating_store.reorder_attempts("TestApp", attempts)
print(f"reordered   -> {[a['method'] for a in reordered]}")