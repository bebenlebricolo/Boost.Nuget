#!/bin/python

import argparse
from enum import Enum
from functools import total_ordering
import shutil
import subprocess
import sys
from pathlib import Path
from shutil import which
from typing import Optional, cast
import requests
import regex
import py7zr
import multiprocessing

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

@total_ordering
class ErrorSensitivity(Enum) :
    LOW = 0
    MID = 1
    HIGH = 2
    UNKNOWN = 3

    def __lt__(self, other) -> bool:                #type: ignore
        if self.__class__ is other.__class__ :      #type: ignore
            return self.value < other.value         #type: ignore
        return NotImplemented

    def __gt__(self, other) -> bool:                #type: ignore
        if self.__class__ is other.__class__ :      #type: ignore
            return self.value > other.value         #type: ignore
        return NotImplemented

    def __ge__(self, other) -> bool:                #type: ignore
        if self.__class__ is other.__class__ :      #type: ignore
            return self.value >= other.value        #type: ignore
        return NotImplemented

    def __le__(self, other) -> bool:                #type: ignore
        if self.__class__ is other.__class__ :      #type: ignore
            return self.value <= other.value        #type: ignore
        return NotImplemented

    @staticmethod
    def from_string(text : str):
        match text :
            case "LOW" :
                return ErrorSensitivity.LOW
            case "MID" :
                return ErrorSensitivity.MID
            case "HIGH" :
                return ErrorSensitivity.HIGH
            case _pass:
                return ErrorSensitivity.UNKNOWN

    @staticmethod
    def get_available_values() -> list[str] :
        values = [ErrorSensitivity.LOW, ErrorSensitivity.MID, ErrorSensitivity.HIGH]
        text = [str(x).split(".")[1] for x in values]
        return text

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

def build_boost_libraries(extracted_folder : Path, rebuild : bool = False, sensitivity : ErrorSensitivity = ErrorSensitivity.LOW) -> bool :
    print("Starting boost build system")

    # Identify visual studio environment
    vcvars64 : Optional[Path] = None
    if get_platform() == "win32" :
        vcvars64 = find_visual_studio_env()
        if vcvars64 == None :
            print("Will build with default build system")


    boost_stage_dir = extracted_folder.joinpath("stage")
    b2_executable = find_b2_executable_in_folder(extracted_folder)
    if b2_executable != None and not rebuild:
        print("Skipping bootstrapping task")
    else :
        bootstrap_commands : list[str] = []
        if vcvars64 != None :
            bootstrap_commands = [vcvars64.absolute().as_posix(), "&"]

        if get_platform() == "win32" :
            bootstrap_commands.append("bootstrap.bat")
        else :
            bootstrap_commands.extend(["bash", "bootstrap.sh"])

        bootstap_result = subprocess.run(bootstrap_commands, shell=True, cwd=extracted_folder)
        if bootstap_result.returncode != 0 :
            print("Caught failure from bootstrap script. Stopping now.")
            return False
        b2_executable = find_b2_executable_in_folder(extracted_folder)




    build_jobs_count = (multiprocessing.cpu_count() - 2)
    b2_executable = cast(Path, b2_executable)
    options = [
        f"-j{build_jobs_count}",
        "link=shared",
        "architecture=x86",
        "address-model=64",
        "threading=multi",
        "runtime-link=shared",
        "--build-type=minimal",
        "stage",
    ]

    commands : list[str] = []
    commands.append(b2_executable.name)
    commands.extend(options)

    if boost_stage_dir.exists():
        print("Found pre-existing build artifacts")
        if rebuild :
            print("Rebuild flag was provided : will trigger full boost rebuild.")
            commands.append("-a")
            shutil.rmtree(boost_stage_dir, ignore_errors=True)
        else :
            print("Skipping build")
            return True

    build_result = subprocess.run(commands, shell=True, cwd=extracted_folder)
    if sensitivity >= ErrorSensitivity.MID and build_result.returncode != 0 :
        print("/!\\ Boost build failed.")
        return False

    print("Boost build succeeded")
    return True

def ensure_directory_exists(directory : Path, clean_first : bool = False) :
    if directory.exists() and clean_first :
        shutil.rmtree(directory, ignore_errors=True)
        directory.mkdir()
    else :
        directory.mkdir()


def find_visual_studio_env() -> Optional[Path]:
    vswhere_cmd : list[str] = [
        "vswhere",
        "-property",
        "installationPath"
    ]
    if which("vswhere") is None :
        print("Couldn't locate vswhere cmdlet in this environment. Please check it is available, for instance by adding its path to your ENV.")
        return None
    cmd_result = subprocess.run(vswhere_cmd, shell=True, capture_output=True, text=True)
    if cmd_result.returncode != 0 :
        print(f"Vswhere command failed : output was {cmd_result.stdout}")
        print(f"Vswhere command failed : error stream was {cmd_result.stderr}")
        return None

    install_location = Path(cmd_result.stdout.splitlines()[0])
    vcvars64 = install_location.rglob("vcvars64.bat")
    vcvars64 = [x.absolute() for x in vcvars64]

    if len(vcvars64) != 0 :
        return vcvars64[0]

    print("Could not find vcvars64.bat script")
    return None

def main(args : list[str]) -> int:
    default_sensitivity_str = str(ErrorSensitivity.LOW).split('.')[1]


    parser = argparse.ArgumentParser("Boost.Nuget", description="Builds boost on this system and packs resulting objects (shared libraries for now) in nuget packages")
    parser.add_argument("-o","--output", help="Output directory", required=False)
    parser.add_argument("-r", "--release", help="Boost release number", default=BOOST_LATEST_STABLE, required=False)
    parser.add_argument("-a", "--author", help="Author of the Nuget package", required=True)
    parser.add_argument("--rebuild", help="Forces the build system to rebuild all objects, otherwise, caching will be performed", required=False, default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument("--no-cache", help="Forces the script to remove the .cache directory and start from scratch", required=False, default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument("--error-sensitivity",
                        help="This script is not very sensitive to build errors"
                        "(because small non-important build errors can break the"
                        " operation and don't affect produced binaries quality)."
                        f" Set this flag to {ErrorSensitivity.get_available_values()}. Defaults to {default_sensitivity_str}",
                        required=False,
                        default=default_sensitivity_str)

    parsed = parser.parse_args(args)
    author = parsed.author
    base_output_dir = Path(parsed.output) if parsed.output != None else None
    release = parsed.release
    rebuild = parsed.rebuild
    no_cache = parsed.no_cache
    error_sensitivity = ErrorSensitivity.from_string(parsed.error_sensitivity)
    if error_sensitivity == ErrorSensitivity.UNKNOWN :
        print(f"Error sensitivity flag not set properly. Value should be one of the following : {ErrorSensitivity.get_available_values()}")
        parser.print_help()
        return 1

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
        shutil.rmtree(base_output_dir)

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

    success = build_boost_libraries(extracted_folder, rebuild, error_sensitivity)
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
        find_visual_studio_env()
    elif get_platform() == "linux" :
        templates_folder = "linux"
    else :
        templates_folder = "other"

    nuspec_folder = cache_dir.joinpath(NUSPEC_DIRECTORY)
    ensure_directory_exists(nuspec_folder, True)
    templates_folder = SCRIPT_DIR.joinpath(templates_folder)
    success = substitute_templates(templates_folder, nuspec_folder, release, author)

    if not success :
        print("Encountered errors. Aborting")
        return 1

    nuspecs_files = [x.absolute() for x in nuspec_folder.glob("*.nuspec")]
    targets_files = templates_folder.glob("*.targets")
    to_be_copied : list[Path] = []
    to_be_copied.extend(nuspecs_files)
    to_be_copied.extend(targets_files)

    print("Copying necessary *.nuspec and *.targets to boost extracted folder")
    for target in to_be_copied :
        dest = extracted_folder.joinpath(target.name)
        shutil.copyfile(target, dest)

    print("Starting packaging")
    for nuspec in nuspecs_files :
        command : list[str] = [
            "nuget",
            "pack",
            nuspec.name,
            "-OutputDirectory",
            base_output_dir.absolute().as_posix()
        ]
        pack_result = subprocess.run(command, shell=True, cwd=extracted_folder)
        if pack_result.returncode != 0 :
            print(f"Caught error while packing for nuspec {nuspec.name}")
            return 1



    print("Done !")
    return 0

if __name__ == "__main__" :
    exit(main(sys.argv[1:]))