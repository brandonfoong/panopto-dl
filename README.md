# panopto-dl
A script to rip Panopto recordings in the highest resolution available

## Installation

panopto-dl requires [Python 3.+](https://www.python.org/downloads/).
After installing Python, install the following pip packages using `pip install` or its equivalent:

1. `zeep`
2. `beautifulsoup4`

panopto-dl also requires [FFmpeg](https://ffmpeg.org/download.html) to be installed.  The FFmpeg executable (`ffmpeg` or `ffmpeg.exe`) should be placed in the same directory as the `panopto-dl.py` file. Alternatively, you may specify the directory that contains the FFmpeg executable in your PATH variable.

## How to Use

```
py panopto-dl.py PANOPTO_URL
```

If `PANOPTO_URL` specifies a link to a single Panopto session, it will download that individual webcast. However, if `PANOPTO_URL` links to a Panopto folder, it will download the contents of that folder, along with all subfolders under it, recursively.

### 1. With .ASPXAUTH cookie

The `-c ASPXAUTH_COOKIE` flag can be used to provide the required authentication credentials. The .ASPXAUTH cookie can be found by going into Developer Tools > Storage > Cookies in most browsers.

### 2. Using NUS Single Sign-On (NUS users only)

NUS users can use their NUSNET account to directly sign in to panopto-dl by using the `-u DOMAIN\USERNAME` and `-p PASSWORD` flags. For some \*nix shells, you may need to delimit the backslash, i.e. type `DOMAIN\\USERNAME` instead.

## Panopto API Endpoints

panopto-dl uses the following RESTful API endpoints to retrieve webcast information:

1. `/Panopto/Services/Data.svc/GetFolderInfo` to retrieve folder names and subfolders
2. `/Panopto/Services/Data.svc/GetSessions` to retrieve folder contents
3. `/Panopto/Pages/Viewer/DeliveryInfo.aspx` to retrieve webcast names and streams, and
4. `/Panopto/Pages/Viewer/Image.aspx` to retrieve slides (for slideshow recordings)

It also uses the following SOAP API to get the direct link to the podcast encode: `/Panopto/PublicAPI/4.6/SessionManagement.svc?singleWsdl`

Disclaimer: AFAIK, the RESTful APIs are **not** officially supported as part of Panopto's public API, and thus, this script *may* break at any time.