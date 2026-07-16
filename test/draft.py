from pathlib import Path

txt_path = Path(__file__).parent / "1.txt"
new_folder = Path(__file__).parent / "new_flder" / "inside"
new_path = new_folder / "2.txt"

if new_folder.is_dir():
    print("T")
else:
    new_folder.mkdir(parents=True, exist_ok=True)

txt_path.replace(new_path)
