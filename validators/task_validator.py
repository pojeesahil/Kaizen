import re

class TaskValidator:

    EXTENSIONS = {
        "python": ".py",
        "py": ".py",
        "c++": ".cpp",
        "cpp": ".cpp",
        "c": ".c",
        "java": ".java",
        "javascript": ".js",
        "js": ".js",
        "typescript": ".ts",
        "ts": ".ts",
        "html": ".html",
        "css": ".css",
        "json": ".json",
        "markdown": ".md",
        "md": ".md"
    }

    def validate(self, plan):
        query = plan["query"].lower()

        language = self.extract_language(query)
        filename = self.extract_filename(query)

        if filename and language:
            filename = self.correct_extension(filename, language)

        return {
            "valid": True,
            "reason": "Valid",
            "language": language,
            "filename": filename
        }

    def extract_language(self, query):
        for language in self.EXTENSIONS:
            if re.search(rf"\b{re.escape(language)}\b", query):
                return language
        return None

    def extract_filename(self, query):
        match = re.search(r"([a-zA-Z0-9_\-]+\.[a-zA-Z0-9]+)", query)
        if match:
            return match.group(1)

        match = re.search(
            r"(?:create|make|generate|edit|modify|update|delete)\s+([a-zA-Z0-9_\-]+)",
            query
        )
        if match:
            return match.group(1)

        return None

    def correct_extension(self, filename, language):
        extension = self.EXTENSIONS.get(language)

        if not extension:
            return filename

        if "." not in filename:
            return filename + extension

        base = filename.rsplit(".", 1)[0]
        return base + extension