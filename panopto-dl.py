import argparse
import re
import requests
import json
import os
import subprocess
import shutil
import logging

from bs4 import BeautifulSoup
from zeep import Client, Transport

PANOPTO_BASE = ""
TEMP_DIR = ".tmp/"
TERM_WIDTH = "<{}".format(shutil.get_terminal_size((80, 20))[0] - 1)

s = requests.session()

# HELPER FUNCTIONS

def login(username, password):
    """
    Login to Panopto using username/password combination
    Currently configured to log in to NUS SSO (nuscast.ap.panopto.com or mediaweb.ap.panopto.com), change accordingly for other login sequences
    Returns True if login is successful, and False otherwise
    """
    login_page = s.get("{}/Panopto/Pages/Auth/Login.aspx?instance=NUSCAST&AllowBounce=true".format(PANOPTO_BASE))
    url = login_page.url
    resp = s.post(url, {"UserName": username, "Password": password, "AuthMethod": "FormsAuthentication"})
    parser = BeautifulSoup(resp.text, "html.parser")
    saml = parser.find("input", {"name": "SAMLResponse"})
    if saml != None:
        s.post("{}/Panopto/Pages/Auth/Login.aspx".format(PANOPTO_BASE), {"SAMLResponse": saml.get("value"),\
                                                                         "RelayState": "{}/Panopto/Pages/Sessions/List.aspx".format(PANOPTO_BASE)})
        return True
    return False

def set_cookie(auth_cookie):
    """
    Login to Panopto by setting .ASPXAUTH cookie
    This *should* work regardless of whichever Panopto subdomain you"re using
    Returns True if login is successful, and False otherwise
    """
    s.cookies = requests.utils.cookiejar_from_dict({".ASPXAUTH": auth_cookie})
    am = Client("{}/Panopto/PublicAPI/4.6/AccessManagement.svc?singleWsdl".format(PANOPTO_BASE), transport=Transport(session=s))
    # TODO: Find a better way to check for successful login instead of relying on the SOAP API throwing an error
    try:
        am.service.GetSelfUserAccessDetails()
    except:
        return False
    return True

def json_api(endpoint, params=dict(), post=False, paramtype="params"):
    """
    Interact with the Panopto REST API and parses JSON as a python dict
    Returns a dict if successful, and False otherwise
    """
    if post:
        r = s.post(PANOPTO_BASE + endpoint, **{paramtype: params})
    else:
        r = s.get(PANOPTO_BASE + endpoint, **{paramtype: params})
    if not r.ok:
        return None
    else:
        return json.loads(r.text)

def clean(string):
    """
    Returns the input string with all filename-invalid characters replaced with underscores
    """
    return re.sub("[^\w\-_\. ]", "_", string)

def dl_stream(url, out_fp):
    """
    Downloads the stream specified in url to out_fp
    """
    subprocess.call(["ffmpeg", "-loglevel", "fatal",\
                     "-y",\
                     "-i", url,\
                     "-c", "copy",\
                     out_fp])

def create_black_screen(ref_fp, dur, out_fp):
    """
    Creates a black screen for the required duration, based on the reference video's resolution
    Apparently HLS transport streams have a fixed tbn of 90kHz? -> magic number 90k
    """
    subprocess.call(["ffmpeg", "-loglevel", "fatal",\
                     "-y",\
                     "-i", ref_fp,\
                     "-preset", "ultrafast",\
                     "-vf", "geq=0:128:128",\
                     "-t", str(round(dur, 3)),\
                     "-video_track_timescale", "90k",\
                     out_fp])

def create_slide_video(img_fp, dur, out_fp):
    """
    Creates a video of the specified slide for the required duration
    """
    subprocess.call(["ffmpeg", "-loglevel", "fatal",\
                     "-y",\
                     "-loop", "1",\
                     "-i", img_fp,\
                     "-c:v", "libx264",\
                     "-preset", "ultrafast",\
                     "-t", str(round(dur, 3)),\
                     "-pix_fmt", "yuv420p",\
                     out_fp])

def combine_streams(stream_lst, out_fp):
    """
    Muxes all streams down into a single file at out_fp
    """
    streams = []
    mapping= []
    metadata = []
    disp = []

    for idx, stream in enumerate(stream_lst):
        if stream["Type"] == "Screen" or stream["Type"] == "Slides":
            streams += ["-f", "concat"]
            mapping += ["-map", "{}:v:0".format(idx)]
            metadata += ["-metadata:s:v:{}".format(idx), "title={}".format(stream["Type"])]
            disp += ["-disposition:v:{}".format(idx), "default"]
        elif stream["Type"] == "Video":
            mapping += ["-map", "{}:v:0".format(idx), "-map", "{}:a:0".format(idx)]
            metadata += ["-metadata:s:v:{}".format(idx), "title={}".format(stream["Type"])]
            disp += ["-disposition:v:{}".format(idx), "none"]
        elif stream["Type"] == "Audio":
            mapping += ["-map", "{}:a:0".format(idx)]
        streams += ["-i", stream["Filepath"]]

    subprocess.call(["ffmpeg", "-loglevel", "fatal", "-y",\
                     *streams,\
                     "-c", "copy",\
                     *mapping,\
                     *metadata,\
                     *disp,\
                     out_fp])

def dl_folder(folder_id, directory="Webcasts/"):
    """
    Download all webcasts from the specified folder and all folders under it to the selected directory
    """
    folder_info = json_api("/Panopto/Services/Data.svc/GetFolderInfo", {"folderID": folder_id}, True, "json")

    if not folder_info: # Unable to retrieve folder info (insufficient permissions)
        print("[Warning] Could not retrieve info for folder ID: {}".format(folder_id))
        return None

    sessions = json_api("/Panopto/Services/Data.svc/GetSessions", {"queryParameters": {"query": None,
                                                                                       "folderID": folder_id,
                                                                                       "sortColumn": 1,
                                                                                       "sortAscending": True,
                                                                                       "getFolderData": True}}, True, "json")
    folder_name = folder_info["d"]["Name"]
    sub_dir = directory + clean(folder_name) + "/"

    if not os.path.exists(sub_dir):
        os.makedirs(sub_dir)

    print("Downloading folder: {}".format(folder_name))

    # Download all webcasts in the directory
    for idx, session in enumerate(sessions["d"]["Results"]):
        dl_session(session["DeliveryID"], sub_dir, "[{}/{}] ".format(idx + 1, len(sessions["d"]["Results"])))

    # Download all subfolders
    for subfolder in sessions["d"]["Subfolders"]:
        dl_folder(subfolder["ID"], sub_dir)

def dl_session(session_id, directory="Webcasts/", prefix = ""):
    """
    Downloads the given webcast to the selected directory
    """
    delivery_info = json_api("/Panopto/Pages/Viewer/DeliveryInfo.aspx", {"deliveryId": session_id,
                                                                         "responseType": "json"}, True, "data")

    if not delivery_info or "Delivery" not in delivery_info: # Unable to retrieve session info (insufficient permissions)
        print("[Warning] Could not retrieve info for webcast ID: {}".format(session_id))
        return None

    session_name = delivery_info["Delivery"]["SessionName"]
    print("{}Downloading webcast: {}".format(prefix, session_name))

    # Create template filename
    temp_fp = TEMP_DIR + clean(session_name) + "_{}.mp4"
    output_fp = directory + clean(session_name) + ".{}"

    # If only the mp4 podcast is available, download it
    if delivery_info["Delivery"]["IsPurgedEncode"]:
        print(" -> Downloading video podcast...", end="\r")
        sm = Client("{}/Panopto/PublicAPI/4.6/SessionManagement.svc?singleWsdl".format(PANOPTO_BASE), transport=Transport(session=s))
        sess_info = sm.service.GetSessionsById(sessionIds=session_id)
        embed_stream = sess_info[0]['IosVideoUrl']
        dl_stream(embed_stream, output_fp.format("mp4"))
        print(" -> Video podcast downloaded!   ")

    # Otherwise, download all the available streams and splice them together
    else:
        streams = delivery_info["Delivery"]["Streams"]
        # Split the streams into three categories - audio, video and screen recordings
        av_streams = list(filter(lambda x: x["Tag"] == "AUDIO" or x["Tag"] == "DV", streams))
        screen_streams = list(filter(lambda x: x["Tag"] == "SCREEN" or x["Tag"] == "OBJECT", streams))
        # Extract Powerpoint slides for webcasts that are PPT slides + audio recording
        ppt_slides = list(filter(lambda x: x["EventTargetType"] == "PowerPoint", delivery_info["Delivery"]["Timestamps"]))
        
        # Handle some potential edge cases and exit this function without downloading if they occur
        # I don't think that there can be >1 audio or video stream, but just flag it out anyways
        if len(av_streams) > 1:
            print("[Error] Found more than 1 audio or video stream")
            return None
        # 0 streams - what the hell is going on here?
        if len(streams) == 0:
            print("[Error] No streams found")
            return None
        # Streams with unidentified tags -  needs further testing
        if len(streams)  - len(av_streams) - len(screen_streams)!= 0:
            print("[Error] Unidentified streams")
            return None

        # Create temp directory to do our work in
        if not os.path.exists(TEMP_DIR):
            os.makedirs(TEMP_DIR)
        
        # Keep track of the streams we've downloaded
        # Stored as a list of {STREAM_TYPE, FILEPATH} dicts
        downloaded_streams = []
        
        # SCREEN/OBJECT streams: Download all and splice them into a single file
        if len(screen_streams) > 0:
            # 1. Download all video files to TEMP_DIR and record the segments
            segments = []
            for idx, screen in enumerate(screen_streams):
                print(" -> Downloading screen recording {} of {}...".format(idx + 1, len(screen_streams)), end="\r")
                screen_fp = "video-{}.mp4".format(idx)
                dl_stream(screen["StreamUrl"], TEMP_DIR + screen_fp)
                for segment in screen["RelativeSegments"]:
                    segment["File"] = screen_fp
                    segment["StreamDuration"] = screen["RelativeEnd"] - screen["RelativeStart"]
                    segments.append(segment)

            # 2. Process segements
            for idx, segment in enumerate(segments):
                if idx == len(segments) - 1:
                    next_start = delivery_info["Delivery"]["Duration"]
                else:
                    next_start = segments[idx + 1]["RelativeStart"]
                # If there is a gap between the end of this segment and the start of the next (or end of the video), attempt to supplement with additional video from the source
                # If there is insufficient video, supplement with as much as possible
                if round(segment["RelativeStart"] + (segment["End"] - segment["Start"]) - next_start) < 0:
                    segment["End"] = min(segment["StreamDuration"], segment["Start"] + next_start - segment["RelativeStart"])
                # If this causes the end of one segment to be equal to the start of the next, combine them to avoid unnecessary splicing
                if idx < len(segments) - 1 and segment["End"] == segments[idx + 1]["Start"] and segment["File"] == segments[idx + 1]["File"]:
                    segment["End"] = segments[idx + 1]["End"]
                    segments.pop(idx + 1)

            # 3. Create concat demuxer file
            black_count = 0
            total_time = 0
            black_fp = TEMP_DIR + "black-{}.mp4"
            demux_fp = TEMP_DIR + "screen.txt"

            with open(demux_fp, "a") as demux:
                for segment in segments:
                    if round(segment["RelativeStart"] - total_time, 3) > 0:
                        # If there is a gap between the total running time and the start of the next segment, create a black screen to fill the difference
                        create_black_screen(TEMP_DIR + segment["File"], segment["RelativeStart"] - total_time, black_fp.format(black_count))
                        demux.write("file black-{}.mp4\n".format(black_count))
                        total_time = segment["RelativeStart"]
                        black_count += 1
                    # Add in details for the next file segment
                    demux.write("file {}\n".format(segment["File"]))
                    demux.write("inpoint {:.3f}\n".format(segment["Start"]))
                    demux.write("outpoint {:.3f}\n".format(segment["End"]))
                    total_time += segment["End"] - segment["Start"]
                # Create one last black screen, if necessary
                if round(delivery_info["Delivery"]["Duration"] - total_time, 3) > 0:
                    create_black_screen(TEMP_DIR + segment["File"], delivery_info["Delivery"]["Duration"] - total_time, black_fp.format(black_count))
                    demux.write("file black-{}.mp4\n".format(black_count))

            downloaded_streams.append({"Type": "Screen", "Filepath": demux_fp})
            print(format(" -> Screen recording(s) downloaded", TERM_WIDTH))

        # PPT slides: Create video file and mux with audio
        if len(ppt_slides) > 0:
            demux_fp = TEMP_DIR + "slides.txt"
            with open(demux_fp, "a") as demux:
                for idx, slide in enumerate(ppt_slides):
                    img_fp = TEMP_DIR + "slide-{}.jpg".format(idx)
                    slide_fp = "slide-{}.mp4".format(idx)
                    print(" -> Downloading slide {} of {}...".format(idx + 1, len(ppt_slides)), end="\r")
                    # Download slide and write it to an image file
                    img = s.post(PANOPTO_BASE + "/Panopto/Pages/Viewer/Image.aspx", {"id": slide["ObjectIdentifier"],
                                                                                     "number": slide["ObjectSequenceNumber"]})
                    if img.headers["Content-Type"] == "image/jpeg":
                        with open(img_fp, "wb") as img_file:
                            img_file.write(img.content)
                    else:
                        print("[Error] Unknown filetype for slide #{}: {}".format(slide["ObjectSequenceNumber"], img.headers["Content-Type"]))
                        exit()
                    # Set start and end times
                    start = 0 if idx == 0 else round(slide["Time"], 3)
                    end = round(delivery_info["Delivery"]["Duration"], 3) if idx == len(ppt_slides) - 1 else round(ppt_slides[idx + 1]["Time"], 3)
                    # Convert slide image to video
                    create_slide_video(img_fp, end - start, TEMP_DIR + slide_fp)
                    # Add details to the concat demuxer
                    with open(TEMP_DIR + "concat.txt", "a") as concat:
                        concat.write("file {}\n".format(slide_fp))

            downloaded_streams.append({"Type": "Slides", "Filepath": demux_fp})
            print(format(" -> Powerpoint slide(s) downloaded!", TERM_WIDTH))
            
        # AUDIO or DV streams
        for av in av_streams:
            stream_type = "video" if av["Tag"] == "DV" else av["Tag"].lower()
            print(" -> Downloading {} stream...".format(stream_type), end="\r")
            av_fp = temp_fp.format(stream_type)
            dl_stream(av["StreamUrl"], av_fp)
            downloaded_streams.append({"Type": stream_type.capitalize(), "Filepath": av_fp})
            print(" -> {} stream downloaded!   ".format(stream_type.capitalize()))

        stream_types = [stream["Type"] for stream in downloaded_streams]
        if "Screen" in stream_types and "Video" in stream_types:
            combine_streams(downloaded_streams, output_fp.format("mkv"))
        elif "Screen" in stream_types or "Slides" in stream_types:
            combine_streams(downloaded_streams, output_fp.format("mp4"))
        else:
            for stream in downloaded_streams:
                shutil.copyfile(stream["Filepath"], output_fp.format("mp4"))
        
        # Cleanup all temporary files
        if os.path.exists(TEMP_DIR):
            shutil.rmtree(TEMP_DIR)

# SETUP ARGPARSE

parser = argparse.ArgumentParser(description="A tool to download Panopto webcasts in the highest available resolution",\
                                 epilog="Note: If both the username/password combination and .ASPXAUTH cookie are specified, the username/password combination will take priority")
parser.add_argument("url", metavar="URL", type=str,\
                    help="Panopto URL that links to a folder or webcast recording")
parser.add_argument("-u", metavar="USERNAME", type=str,\
                    help="NUSNET username (including \"nusstu\\\" prefix)")
parser.add_argument("-p", metavar="PASSWORD", type=str,\
                    help="NUSNET password")
parser.add_argument("-c", metavar="COOKIE", type=str,\
                    help=".ASPXAUTH cookie")
args = parser.parse_args()

# SCRIPT STARTS HERE

logging.getLogger("zeep").setLevel(logging.ERROR)

if not shutil.which("ffmpeg"):
    print("[Error] FFmpeg not found: The FFmpeg executable can be downloaded from https://ffmpeg.org/download.html")
    exit()

url_match = re.search("^(?:https?://)?(?P<base>(?:\w+\.)+panopto\.(?:eu|com))/Panopto/Pages/"+\
                      "(?:Sessions/List.aspx#folderID=(?:\"|%22)(?P<folder>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:\"|%22)|"+\
                      "(?:Viewer|Embed).aspx\?id=(?P<session>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}))(?:&\w+=(?:\w|%)+)*$", args.url)
if not url_match:
    print("[Error] Invalid Panopto folder or session URL")
    exit()

PANOPTO_BASE = "https://{}".format(url_match.group("base"))
folder_id = url_match.group("folder")
session_id = url_match.group("session")

if (args.u and args.p) or args.c:
    if not (login(args.u, args.p) or set_cookie(args.c)):
        print("[Warning] Failed to log in: panopto-dl will continue to run, but it may not be able to retrieve the webcasts")
else:
    print("[Warning] Login credentials not specified: panopto-dl will continue to run, but it may not be able to retrieve the webcasts")

if os.path.exists(TEMP_DIR):
    shutil.rmtree(TEMP_DIR)

if folder_id:
    dl_folder(folder_id)
elif session_id:
    if not os.path.exists("Webcasts/"):
        os.makedirs("Webcasts/")
    dl_session(session_id)
