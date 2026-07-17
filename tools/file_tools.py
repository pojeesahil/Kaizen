from pathlib import Path
import shutil

class FileTools:

    def __init__(self, workspace="workspace"):
        self.workspace = Path(workspace)
        self.workspace.mkdir(exist_ok=True)

    def _path(self, filename):
        return self.workspace / filename

    def create_file(self, filename, content=""):
        path = self._path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def edit_file(self, filename, content):
        path = self._path(filename)
        if not path.exists():
            raise FileNotFoundError(f"{filename} not found.")
        path.write_text(content, encoding="utf-8")

    def delete_file(self, filename):
        path = self._path(filename)
        if path.exists():
            path.unlink()

    def create_folder(self, foldername):
        self._path(foldername).mkdir(parents=True, exist_ok=True)

    def delete_folder(self, foldername):
        path = self._path(foldername)
        if path.exists():
            shutil.rmtree(path)

    def read_file(self, filename):
        path = self._path(filename)
        if not path.exists():
            raise FileNotFoundError(f"{filename} not found.")
        return path.read_text(encoding="utf-8")

    def list_files(self):
        return [
            str(file.relative_to(self.workspace))
            for file in self.workspace.rglob("*")
            if file.is_file()
        ]

def main():
    tools = FileTools()

    tools.create_folder("demo")
    tools.create_file("demo/test.py", 'print("Hello World")')
    print(tools.read_file("demo/test.py"))

    tools.edit_file("demo/test.py", 'print("Updated")')
    print(tools.read_file("demo/test.py"))

    print("\nFiles:")
    for file in tools.list_files():
        print(file)

    tools.delete_file("demo/test.py")
    tools.delete_folder("demo")

if __name__ == "__main__":
    main()