# panopto-dl
A script to rip Panopto recordings in the highest resolution available

## Installation

panopto-dl requires [Python 3.+](https://www.python.org/downloads/).
After installing Python, install the following pip packages using `pip install` or its equivalent:

1. `zeep`
2. `beautifulsoup4`

panopto-dl also requires [FFmpeg](https://ffmpeg.org/download.html) to be installed.  The FFmpeg executable (`ffmpeg` or `ffmpeg.exe`) should be placed in the same directory as the `panopto-dl.py` file, or specified in your PATH variable.

## How to Use

```
py panopto-dl.py PANOPTO_URL
```

If `PANOPTO_URL` specifies a link to a single Panopto session, it will download that individual webcast. However, if `PANOPTO_URL` links to a Panopto folder, it will download the contents of that folder, along with all subfolders under it, recursively.

### 1. With .ASPXAUTH cookie

The `-c ASPXAUTH_COOKIE` flag can be used to provide the required authentication credentials. The .ASPXAUTH cookie can be found by going into Developer Tools > Storage > Cookies

### 2. Using NUS Single Sign-On (NUS users only)

NUS users can use their NUSNET account to directly sign in to panopto-dl by using the `-u DOMAIN\USERNAME` (or `-u DOMAIN\\USERNAME` for \*nix shells) and `-p PASSWORD` flags.
