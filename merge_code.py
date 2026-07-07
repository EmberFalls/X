import os

# Name of your final file
output_file = 'project_codebase.txt'

# Explicitly list the file extensions you want to collect from your folder
target_extensions = ('.py', '.json', '.js', '.css', '.md', '.env', 'README', 'requirements')
# Skip the output file and the script itself to prevent infinite loops
ignored_files = {output_file, 'merge_code.py'}

with open(output_file, 'w', encoding='utf-8') as outfile:
    # Read the current directory
    for filename in sorted(os.listdir('.')):
        # Check if the item is a target file and not ignored
        if (filename.endswith(target_extensions) or filename in ('README', 'requirements')) and filename not in ignored_files:
            if os.path.isfile(filename):
                # Write a clear visual header for the AI
                outfile.write(f"\n\n=========================================\n")
                outfile.write(f"FILE: {filename}\n")
                outfile.write(f"=========================================\n\n")
                
                try:
                    with open(filename, 'r', encoding='utf-8') as infile:
                        outfile.write(infile.read())
                    print(f"Successfully added: {filename}")
                except Exception as e:
                    outfile.write(f"[Error reading file {filename}: {e}]\n")

print(f"\nAll done! Upload '{output_file}' directly into Perplexity.")
