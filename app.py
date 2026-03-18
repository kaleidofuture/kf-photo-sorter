"""KF-PhotoSorter — Extract EXIF metadata from photos and organize them."""

import streamlit as st

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass  # pillow-heif not available, HEIC files won't be supported

st.set_page_config(
    page_title="KF-PhotoSorter",
    page_icon="\U0001F4F7",
    layout="wide",
)

from components.header import render_header
from components.footer import render_footer
from components.i18n import t

import zipfile
import io
import csv
from collections import defaultdict

import exifread
from PIL import Image

# --- Header ---
render_header()
st.info("💻 " + t("desktop_recommended"))

MAX_ZIP_SIZE_MB = 50


def extract_exif(file_bytes: bytes, filename: str) -> dict:
    """Extract EXIF data from image bytes."""
    result = {
        "filename": filename,
        "date": None,
        "camera_make": None,
        "camera_model": None,
        "gps_lat": None,
        "gps_lon": None,
        "width": None,
        "height": None,
    }

    try:
        tags = exifread.process_file(io.BytesIO(file_bytes), details=False)

        # Date
        for date_tag in ["EXIF DateTimeOriginal", "EXIF DateTimeDigitized", "Image DateTime"]:
            if date_tag in tags:
                result["date"] = str(tags[date_tag])
                break

        # Camera
        if "Image Make" in tags:
            result["camera_make"] = str(tags["Image Make"]).strip()
        if "Image Model" in tags:
            result["camera_model"] = str(tags["Image Model"]).strip()

        # GPS
        gps_lat = tags.get("GPS GPSLatitude")
        gps_lat_ref = tags.get("GPS GPSLatitudeRef")
        gps_lon = tags.get("GPS GPSLongitude")
        gps_lon_ref = tags.get("GPS GPSLongitudeRef")

        if gps_lat and gps_lon:
            result["gps_lat"] = _convert_gps(gps_lat, gps_lat_ref)
            result["gps_lon"] = _convert_gps(gps_lon, gps_lon_ref)

    except Exception:
        pass

    # Image dimensions via Pillow
    try:
        img = Image.open(io.BytesIO(file_bytes))
        result["width"], result["height"] = img.size
    except Exception:
        pass

    return result


def _convert_gps(coord_tag, ref_tag) -> float | None:
    """Convert EXIF GPS coordinates to decimal degrees."""
    try:
        values = coord_tag.values
        d = float(values[0].num) / float(values[0].den)
        m = float(values[1].num) / float(values[1].den)
        s = float(values[2].num) / float(values[2].den)
        decimal = d + m / 60.0 + s / 3600.0
        if ref_tag and str(ref_tag) in ("S", "W"):
            decimal = -decimal
        return round(decimal, 6)
    except Exception:
        return None


# --- Main Content ---
st.subheader(t("upload_title"))
st.caption(t("upload_help").format(max_mb=MAX_ZIP_SIZE_MB))

upload_mode = st.radio(
    t("upload_mode"),
    [t("mode_zip"), t("mode_files")],
    horizontal=True,
)

if upload_mode == t("mode_zip"):
    uploaded_file = st.file_uploader(
        t("upload_prompt"),
        type=["zip"],
    )
    uploaded_files = None
else:
    uploaded_file = None
    uploaded_files = st.file_uploader(
        t("upload_prompt"),
        type=["jpg", "jpeg", "png", "heic", "heif", "tiff", "tif"],
        accept_multiple_files=True,
    )

photo_data = []
processing_error = None

if uploaded_file is not None:
    # ZIP mode
    file_size_mb = uploaded_file.size / (1024 * 1024)
    if file_size_mb > MAX_ZIP_SIZE_MB:
        st.error(t("file_too_large").format(max_mb=MAX_ZIP_SIZE_MB, size_mb=round(file_size_mb, 1)))
    else:
        with st.spinner(t("processing")):
            try:
                zip_bytes = uploaded_file.read()
                zf = zipfile.ZipFile(io.BytesIO(zip_bytes))

                image_extensions = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".heic", ".heif"}

                for name in zf.namelist():
                    # Skip directories and hidden files
                    if name.endswith("/") or name.startswith("__MACOSX"):
                        continue
                    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
                    if ext not in image_extensions:
                        continue

                    file_bytes = zf.read(name)
                    exif = extract_exif(file_bytes, name)
                    photo_data.append(exif)

            except zipfile.BadZipFile:
                processing_error = "bad_zip"
            except Exception as e:
                processing_error = str(e)

elif uploaded_files:
    # Direct file selection mode
    with st.spinner(t("processing")):
        try:
            for uf in uploaded_files:
                file_bytes = uf.read()
                exif = extract_exif(file_bytes, uf.name)
                photo_data.append(exif)
        except Exception as e:
            processing_error = str(e)

if processing_error:
    if processing_error == "bad_zip":
        st.error(t("bad_zip"))
    else:
        st.error(t("error").format(error=processing_error))
elif uploaded_file is not None or uploaded_files:
    if not photo_data:
        st.warning(t("no_images"))
    else:
        st.success(t("found_images").format(count=len(photo_data)))

        # --- Summary tabs ---
        tab_all, tab_date, tab_camera = st.tabs([
            t("tab_all"), t("tab_by_date"), t("tab_by_camera")
        ])

        with tab_all:
            # Display as table
            display_data = []
            for p in photo_data:
                row = {
                    t("col_filename"): p["filename"],
                    t("col_date"): p["date"] or "-",
                    t("col_camera"): f"{p['camera_make'] or ''} {p['camera_model'] or ''}".strip() or "-",
                    t("col_size"): f"{p['width']}x{p['height']}" if p["width"] else "-",
                    t("col_gps"): f"{p['gps_lat']}, {p['gps_lon']}" if p["gps_lat"] else "-",
                }
                display_data.append(row)
            st.dataframe(display_data, use_container_width=True)

        with tab_date:
            # Group by date
            by_date = defaultdict(list)
            for p in photo_data:
                date_str = p["date"][:10].replace(":", "-") if p["date"] else t("unknown_date")
                by_date[date_str].append(p)

            for date_key in sorted(by_date.keys()):
                items = by_date[date_key]
                st.markdown(f"**{date_key}** ({len(items)} {t('photos')})")
                for item in items:
                    camera = f"{item['camera_make'] or ''} {item['camera_model'] or ''}".strip()
                    st.caption(f"  {item['filename']}  |  {camera or '-'}")

        with tab_camera:
            # Group by camera
            by_camera = defaultdict(list)
            for p in photo_data:
                camera = f"{p['camera_make'] or ''} {p['camera_model'] or ''}".strip()
                if not camera:
                    camera = t("unknown_camera")
                by_camera[camera].append(p)

            for camera_name in sorted(by_camera.keys()):
                items = by_camera[camera_name]
                st.markdown(f"**{camera_name}** ({len(items)} {t('photos')})")
                for item in items:
                    date_str = item["date"][:10].replace(":", "-") if item["date"] else "-"
                    st.caption(f"  {item['filename']}  |  {date_str}")

        # --- CSV Download ---
        st.markdown("---")
        csv_buffer = io.StringIO()
        fieldnames = ["filename", "date", "camera_make", "camera_model",
                      "width", "height", "gps_lat", "gps_lon"]
        writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
        writer.writeheader()
        for p in photo_data:
            writer.writerow(p)

        st.download_button(
            label=t("download_csv"),
            data=csv_buffer.getvalue(),
            file_name="photo_metadata.csv",
            mime="text/csv",
        )

else:
    st.info(t("no_file"))

# --- Footer ---
render_footer(libraries=["ExifRead", "Pillow"])
