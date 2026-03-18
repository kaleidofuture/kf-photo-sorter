"""KF-PhotoSorter — Extract EXIF metadata from photos and organize them."""

import streamlit as st

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIF_AVAILABLE = True
except ImportError:
    HEIF_AVAILABLE = False

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
import hashlib
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
        "file_size": len(file_bytes),
        "md5": hashlib.md5(file_bytes).hexdigest(),
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


def find_duplicates(photo_data: list[dict]) -> tuple[list[list[dict]], int]:
    """Find duplicate files by MD5 hash. Returns (groups, saveable_bytes)."""
    hash_groups = defaultdict(list)
    for p in photo_data:
        hash_groups[p["md5"]].append(p)

    duplicate_groups = [group for group in hash_groups.values() if len(group) > 1]
    saveable = sum(
        sum(p["file_size"] for p in group[1:])
        for group in duplicate_groups
    )
    return duplicate_groups, saveable


def get_top_largest(photo_data: list[dict], n: int = 20) -> list[dict]:
    """Return top N largest files."""
    return sorted(photo_data, key=lambda p: p["file_size"], reverse=True)[:n]


def format_size(size_bytes: int) -> str:
    """Format bytes to human-readable string."""
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def build_organized_zip(file_map: dict[str, bytes], photo_data: list[dict], convert_heic: bool) -> bytes:
    """Build a ZIP with photos organized into YYYY-MM/ folders.

    Args:
        file_map: filename -> raw bytes mapping
        photo_data: list of EXIF dicts
        convert_heic: if True, convert HEIC files to JPG
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        used_names = set()
        for p in photo_data:
            # Determine folder
            if p["date"]:
                try:
                    date_str = p["date"][:7].replace(":", "-")  # "YYYY-MM"
                except Exception:
                    date_str = "unknown"
            else:
                date_str = "unknown"

            original_name = p["filename"].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            raw_bytes = file_map.get(p["filename"])
            if raw_bytes is None:
                continue

            ext_lower = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
            should_convert = convert_heic and ext_lower in ("heic", "heif") and HEIF_AVAILABLE

            if should_convert:
                try:
                    img = Image.open(io.BytesIO(raw_bytes))
                    jpg_buf = io.BytesIO()
                    img.convert("RGB").save(jpg_buf, format="JPEG", quality=92)
                    raw_bytes = jpg_buf.getvalue()
                    # Change extension
                    base = original_name.rsplit(".", 1)[0]
                    original_name = base + ".jpg"
                except Exception:
                    pass  # Keep original if conversion fails

            # Deduplicate names within the zip
            target_path = f"{date_str}/{original_name}"
            if target_path in used_names:
                base, ext = (original_name.rsplit(".", 1) + [""])[:2]
                counter = 2
                while True:
                    new_name = f"{base}_{counter}.{ext}" if ext else f"{base}_{counter}"
                    target_path = f"{date_str}/{new_name}"
                    if target_path not in used_names:
                        break
                    counter += 1

            used_names.add(target_path)
            zf.writestr(target_path, raw_bytes)

    return buf.getvalue()


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
file_map = {}  # filename -> raw bytes (for ZIP generation)
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
                    file_map[name] = file_bytes
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
                file_map[uf.name] = file_bytes
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

        # --- Duplicate Detection ---
        dup_groups, saveable_bytes = find_duplicates(photo_data)
        if dup_groups:
            dup_count = sum(len(g) - 1 for g in dup_groups)
            st.warning(
                t("duplicate_found").format(
                    count=dup_count,
                    size=format_size(saveable_bytes),
                )
            )
            with st.expander(t("duplicate_details")):
                for i, group in enumerate(dup_groups, 1):
                    st.markdown(f"**{t('duplicate_group')} {i}** (MD5: `{group[0]['md5'][:12]}...`)")
                    for p in group:
                        st.caption(f"  {p['filename']}  ({format_size(p['file_size'])})")

        # --- Summary tabs ---
        tab_all, tab_date, tab_camera, tab_size = st.tabs([
            t("tab_all"), t("tab_by_date"), t("tab_by_camera"), t("tab_size_ranking")
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
                    t("col_filesize"): format_size(p["file_size"]),
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

        with tab_size:
            # Top 20 largest files
            st.markdown(f"**{t('top_largest_title')}**")
            largest = get_top_largest(photo_data, 20)
            size_table = []
            for rank, p in enumerate(largest, 1):
                size_table.append({
                    "#": rank,
                    t("col_filename"): p["filename"],
                    t("col_filesize"): format_size(p["file_size"]),
                    t("col_dimensions"): f"{p['width']}x{p['height']}" if p["width"] else "-",
                    t("col_date"): p["date"][:10].replace(":", "-") if p["date"] else "-",
                })
            st.dataframe(size_table, use_container_width=True)

            total_size = sum(p["file_size"] for p in photo_data)
            st.info(t("total_size_info").format(size=format_size(total_size)))

        # --- CSV Download ---
        st.markdown("---")
        csv_buffer = io.StringIO()
        fieldnames = ["filename", "date", "camera_make", "camera_model",
                      "width", "height", "gps_lat", "gps_lon", "file_size", "md5"]
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

        # --- Organized ZIP Download ---
        st.markdown(f"#### {t('organized_zip_title')}")
        st.caption(t("organized_zip_help"))

        convert_heic = False
        if HEIF_AVAILABLE:
            convert_heic = st.checkbox(t("convert_heic_option"), value=False)

        if st.button(t("generate_organized_zip"), type="primary"):
            with st.spinner(t("generating_zip")):
                organized_bytes = build_organized_zip(file_map, photo_data, convert_heic)
            st.download_button(
                label=t("download_organized_zip"),
                data=organized_bytes,
                file_name="photos_organized.zip",
                mime="application/zip",
                key="download_organized_zip_btn",
            )

else:
    st.info(t("no_file"))

# --- Footer ---
render_footer(libraries=["ExifRead", "Pillow"], repo_name="kf-photo-sorter")
