# Boost.Nuget
Small repository that downloads a revision of C++ boost, builds shared libs and creates a NuGet package.

# Requirements
* You need a python 3 installation greater than python3.10 (to use static type annotations )
* Nuget command line tool should be available from command line

# Usage
```bash
python -m venv .venv
source .venv/bin/activate # or .venv/Scripts/activate on windows
pip install -r requirements.txt

# Let's build and package boost !
python build_package.py -o .package -r 1.86.0 -a yourname --rebuild
```

