#!/bin/python

import argparse
import subprocess
import sys
from pathlib import Path
from shutil import which
from typing import Optional, cast
import requests
import regex
import py7zr

VERSION_TAG = "VERSION"
AUTHOR_TAG = "AUTHOR"
VERSION_UNDERSCORED_TAG = "VERSION_UNDERSCORED"

BOOST_LATEST_STABLE = "1.86.0"
BOOST_DOWNLOAD = "https://archives.boost.io/release/VERSION/source/boost_VERSION_UNDERSCORED.7z"
SOURCEFORGE_DOWNLOAD = "https://sourceforge.net/projects/boost/files/boost/VERSION/boost_VERSION_UNDERSCORED.7z/download"

CACHE_DIRECTORY = ".cache"
NUSPEC_DIRECTORY = "nuspec"
DEFAULT_OUTPUT_DIRECTORY = "Packages"

SCRIPT_DIR = Path(__file__).parent

def check_nuget() -> bool :
    return which("nuget") is not None

def download_boost(release : str, output_file: Path,  source_forged : bool = False) -> bool :
    underscored_release = release.replace(".", "_")
    print(f"Downloading boost release {release}.7z archive")

    if not source_forged :
        link = BOOST_DOWNLOAD.replace(VERSION_UNDERSCORED_TAG, underscored_release).replace(VERSION_TAG, release)
    else :
        link = SOURCEFORGE_DOWNLOAD.replace(VERSION_UNDERSCORED_TAG, underscored_release).replace(VERSION_TAG, release)

    print(f"Downloading from {link}")
    response = requests.get(link)
    if response.status_code == 404 :
        print("Not found in main releases, will try with sourceforge host.")
        return download_boost(release, output_file, True)
    elif response.status_code != 200 :
        print("/!\\ Cannot download boost archive from remote !")
        return False

    data = response.content
    try :
        with open(output_file, 'wb') as file :
            file.write(data)
    except Exception as e :
        print(f"/!\\ Could not download data. Exception : {e}")
        return False

    return True

def substitute_templates(templates_dir : Path, output_dir : Path, release : str, author : str) -> bool :
    templates = templates_dir.glob("*.nuspec.template")
    has_errors = False

    for template in templates :
        filename = template.stem.replace(".template", "")
        output_file = output_dir.joinpath(filename)
        print(f"Replacing tags in template .nuspec file {template} ... ")

        try :
            with open(template, "r") as file :
                content = file.read()
            content = content.replace(VERSION_TAG, release).replace(AUTHOR_TAG, author)

            print(f"Dumping new .nuspec file {output_file} ... ")
            with open(output_file, "w") as file :
                file.write(content)
        except Exception as e :
            print(f"Caught exception {e}")
            has_errors = True
            continue

    return not has_errors


def get_platform() -> str :
    return sys.platform

def unzip_archive(archive : Path, extracted_folder : Path) -> bool :
    try:
        print(f"Unzipping archive to {extracted_folder} ... ")
        with py7zr.SevenZipFile(archive, mode='r') as zipped :
            zipped.extractall(extracted_folder)
    except Exception as e :
        print(f"/!\\ Could not extract archive because : {e}")
        print("Cleaning leftovers ...")
        extracted_folder.rmdir()
        return False
    print("Successfully extracted boost archive")

    return True

def find_b2_executable_in_folder(search_dir : Path) -> Optional[Path] :
    b2_executable = None
    for b2_candidate in search_dir.glob("b2*") :
        b2_executable = b2_candidate

    return b2_executable

def build_boost_libraries(extracted_folder : Path, rebuild : bool = False) -> bool :
    print("Starting boost build system")
    boost_stage_dir = extracted_folder.joinpath("stage")
    if boost_stage_dir.exists() and rebuild:
        print("Cleaning previous build artifacts")
        boost_stage_dir.rmdir()

    b2_executable = find_b2_executable_in_folder(extracted_folder)
    if b2_executable != None:
        print("Skipping bootstrapping task")
    else :
        bootstap_result = subprocess.run(["bash", "bootstrap.sh"], shell=True, cwd=extracted_folder)
        if bootstap_result.returncode != 0 :
            print("Caught failure from bootstrap script. Stopping now.")
            return False
        b2_executable = find_b2_executable_in_folder(extracted_folder)

    b2_executable = cast(Path, b2_executable)
    build_result = subprocess.run([b2_executable.name , "link=shared"],shell=True, cwd=extracted_folder)
    if build_result.returncode != 0 :
        print("/!\\ Boost build failed.")
        return False

    print("Boost build succeeded")
    return True


def main(args : list[str]) -> int:
    parser = argparse.ArgumentParser("Boost.Nuget", description="Builds boost on this system and packs resulting objects (shared libraries for now) in nuget packages")
    parser.add_argument("-o","--output", help="Output directory", required=False)
    parser.add_argument("-r", "--release", help="Boost release number", default=BOOST_LATEST_STABLE, required=False)
    parser.add_argument("-a", "--author", help="Author of the Nuget package", required=True)
    parser.add_argument("--rebuild", help="Forces the build system to rebuild all objects, otherwise, caching will be performed", required=False, default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument("--no-cache", help="Forces the script to remove the .cache directory and start from scratch", required=False, default=False, action=argparse.BooleanOptionalAction)

    parsed = parser.parse_args(args)
    author = parsed.author
    base_output_dir = Path(parsed.output) if parsed.output != None else None
    release = parsed.release
    rebuild = parsed.rebuild
    no_cache = parsed.no_cache

    cache_dir = Path(SCRIPT_DIR).joinpath(CACHE_DIRECTORY)
    if not check_nuget() :
        print("Nuget command line executable couldn't be located on your system. Please add nuget to your Path environment first.")
        return 1

    if not cache_dir.exists():
        print("Creating cache directory")
        cache_dir.mkdir(parents=True)
    elif cache_dir.exists() and no_cache :
        print("Removing old cache directory, starting fresh.")
        cache_dir.rmdir()
        cache_dir.mkdir(parents=True)

    # Default output is in the cache directory
    if base_output_dir == None :
        base_output_dir = SCRIPT_DIR.joinpath(CACHE_DIRECTORY).joinpath(DEFAULT_OUTPUT_DIRECTORY)

    # Creating output directory (and cleaning leftovers if need be)
    if base_output_dir.exists():
        base_output_dir.rmdir()
    print(f"Creating output directory : {base_output_dir}")
    base_output_dir.mkdir(parents=True)

    pattern = regex.compile(r"(\d{1,}\.){2}(\d{1,})")
    matches = pattern.match(release)
    if matches == None:
        print("Wrong format for release. Expected format is XX.YY.ZZ")
        return 1

    boost_archive = cache_dir.joinpath(f"boost_{release}.7z")
    if not boost_archive.exists() :
        success = download_boost(release, boost_archive)
        if not success :
            print("Download failed, aborting.")
            return 1
    else :
        print("Archive already exists. Skipping downloading")


    # Extracting ...
    underscored_release = str(release).replace(".", "_")
    extracted_folder = cache_dir.joinpath(f"boost_{underscored_release}")
    if not extracted_folder.exists():
        success = unzip_archive(boost_archive, cache_dir)
    else :
        print(f"Archive was already extracted to {extracted_folder}. Skipping extraction.")

    success = build_boost_libraries(extracted_folder, rebuild)
    if not success :
        print("Aborting packaging.")
        return 1


    # Building
    #######
    ######
    ## dealing with nuspec template substitutions

    templates_folder = "none"
    if get_platform() == "win32" :
        templates_folder = "windows"
    elif get_platform() == "linux" :
        templates_folder = "linux"
    else :
        templates_folder = "other"

    nuspec_folder = cache_dir.joinpath(NUSPEC_DIRECTORY)
    templates_folder = SCRIPT_DIR.joinpath(templates_folder)
    success = substitute_templates(templates_folder, nuspec_folder, release, author)

    if not success :
        print("Encountered errors. Aborting")
        return 1


    return 0

if __name__ == "__main__" :
    exit(main(sys.argv[1:]))