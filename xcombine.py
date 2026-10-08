import os

# Define the root directory to search and the output Markdown file
root_dir = "./"  # Current folder
output_file = "llm_prompt_code.md"

# Directories you want to completely ignore
ignored_dirs = {".venv", "venv", "env", "__pycache__", ".git", ".idea", ".vscode", "node_modules"}

with open(output_file, "w", encoding="utf-8") as outfile:
    # Optional: Write a helpful primer at the top of the file for the LLM
    outfile.write("# Project Source Code\n\n")
    outfile.write("Below is the combined source code for the project. Please review it.\n\n")

    file_count = 0

    # Walk through all directories and subdirectories
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Modify dirnames in-place to skip ignored directories completely
        dirnames[:] = [d for d in dirnames if d not in ignored_dirs]

        for filename in sorted(filenames):
            # Only process Python files and avoid reading our own output file
            if filename.endswith(".py") and filename != output_file:
                full_path = os.path.join(dirpath, filename)
                # Create a clean relative path for the LLM to understand the file structure
                relative_path = os.path.relpath(full_path, root_dir)

                # Write file tracking metadata in Markdown
                outfile.write(f"## File: `{relative_path}`\n")
                outfile.write("```python\n")

                try:
                    with open(full_path, "r", encoding="utf-8") as infile:
                        outfile.write(infile.read())
                except Exception as e:
                    outfile.write(f"# Error reading file: {e}\n")

                outfile.write("\n```\n\n")
                file_count += 1

print(f"Done! Formatted {file_count} Python files into Markdown at '{output_file}'.")
