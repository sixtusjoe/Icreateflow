"""
Full pipeline orchestrator.
Coordinates: overlay generation → video creation for all accounts.
"""
from pathlib import Path
from . import overlay, video
import database as db


async def generate_post(post_id: int, database) -> dict:
    """
    Generate all outputs (slides + videos) for a post across all accounts.

    Steps:
    1. Get post, slides, brand, accounts, variations
    2. For each account:
       a. Determine final image for each slide (master or replacement)
       b. Apply text overlays → 3:4 slides
       c. Convert to 9:16 slides
       d. Build video with transitions + music
    3. Save output records

    Returns:
        dict with status and output paths per account
    """
    post = await db.get_post(database, post_id)
    if not post:
        raise ValueError(f"Post {post_id} not found")

    brand = await db.get_brand(database, post["brand_id"])
    accounts = await db.get_accounts(database, post["brand_id"])
    slides = await db.get_slides(database, post_id)

    if not slides:
        raise ValueError(f"Post {post_id} has no slides")

    # Get music track path if set
    music_path = None
    if post["music_track_id"]:
        cursor = await database.execute(
            "SELECT file_path FROM music_tracks WHERE id = ?", (post["music_track_id"],)
        )
        track = await cursor.fetchone()
        if track:
            music_path = track["file_path"]

    bg_color = brand["background_color"] or "#000000"
    results = {}

    # Update post status
    await db.update_post(database, post_id, status="generating")

    try:
        for account in accounts:
            account_id = account["id"]
            account_name = account["name"]

            # Output directory
            out_dir = Path("output") / brand["slug"] / post["date"] / account_name / f"post_{post['post_number']}"
            slides_dir = out_dir / "slides"
            slides_dir.mkdir(parents=True, exist_ok=True)

            # Get variations for this account
            variations = await db.get_variations(database, post_id=post_id, account_id=account_id)
            variation_map = {}
            for v in variations:
                # Map slide_id to variation
                variation_map[v["slide_id"]] = v

            # Process each slide
            slide_9x16_paths = []

            for slide in slides:
                slide_num = slide["slide_number"]
                var = variation_map.get(slide["id"])

                # Determine source image
                if var and var["action"] in ("replace", "generate") and var["replacement_image_path"]:
                    source_image = var["replacement_image_path"]
                else:
                    source_image = slide["master_image_path"]

                if not source_image or not Path(source_image).exists():
                    continue

                # Apply overlay
                output_path = str(slides_dir / f"slide_{slide_num:02d}.png")
                result = overlay.apply_overlay(
                    image_path=source_image,
                    slide_type=slide["type"],
                    output_path=output_path,
                    title_text=slide["title_text"],
                    body_text=slide["body_text"],
                    cta_text=slide["cta_text"],
                    bg_color=bg_color,
                )

                slide_9x16_paths.append(result["slide_9x16"])

            # Build video from 9:16 slides
            video_path = None
            if len(slide_9x16_paths) >= 2:
                video_path = str(out_dir / "video.mp4")
                try:
                    video.build_video(
                        slide_paths=slide_9x16_paths,
                        output_path=video_path,
                        music_path=music_path,
                    )
                except Exception as e:
                    video_path = None
                    print(f"Video generation failed for {account_name}: {e}")

            # Save caption
            if post["caption"]:
                (out_dir / "caption.txt").write_text(post["caption"])

            # Create/update output record
            existing = await database.execute(
                "SELECT id FROM outputs WHERE post_id = ? AND account_id = ?",
                (post_id, account_id)
            )
            existing_row = await existing.fetchone()
            if existing_row:
                await db.update_output(
                    database, existing_row["id"],
                    slides_dir=str(slides_dir),
                    video_path=video_path,
                    posting_status="ready"
                )
            else:
                await db.create_output(
                    database, post_id, account_id,
                    slides_dir=str(slides_dir),
                    video_path=video_path,
                    posting_status="ready"
                )

            results[account_name] = {
                "slides_dir": str(slides_dir),
                "video_path": video_path,
                "slide_count": len(slide_9x16_paths),
            }

        await db.update_post(database, post_id, status="scheduled" if post["scheduled_time"] else "draft")

    except Exception as e:
        await db.update_post(database, post_id, status="failed")
        raise

    return {
        "post_id": post_id,
        "accounts": results,
    }
