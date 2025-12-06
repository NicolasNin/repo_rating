# File Selection Prompt

You are analyzing a code repository to identify which files are most important for understanding the project.

## README
$readme_content

## File List (ID: path, size)
$file_list

## Task

Select files that are important for understanding this project's code and architecture.

**EXCLUDE:**
- Generated files (compiled output, bundled assets)
- Data files (JSON data, CSVs, logs)
- Binary files
- Lock files
- Node modules, vendor directories
- Test fixtures and sample data
- Documentation that duplicates README
- Large LLM outputs/reports

**INCLUDE:**
- Source code files
- Configuration files
- README and essential docs
- Entry points and main modules

## Output

Return ONLY the numeric IDs of files to INCLUDE, one per line.
Do not include any other text, explanations, or formatting.

Example output:
1
3
5
7
