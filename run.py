#!/usr/bin/env python3
"""
Advanced Video File Converter
Searches for .mp4 and .mkv files in a directory tree and converts them to optimized MP4 format.
Features: Enhanced progress tracking with detailed metrics and quality-of-life improvements.
"""

import os
import sys
import subprocess
import argparse
import logging
import time
import threading
from pathlib import Path
from typing import List, Tuple, Optional
import shutil
from datetime import datetime, timedelta
import re

# Configure logging
def setup_logging(verbose: bool = False):
    """Setup logging configuration."""
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    log_level = logging.DEBUG if verbose else logging.INFO
    
    # Create logs directory if it doesn't exist
    log_dir = Path('logs')
    log_dir.mkdir(exist_ok=True)
    
    # Only log to file to avoid interfering with progress display
    file_handler = logging.FileHandler(
        log_dir / f'video_converter_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(log_format))
    
    logger = logging.getLogger(__name__)
    logger.setLevel(log_level)
    logger.addHandler(file_handler)
    
    # Add console handler only for verbose mode
    if verbose:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.ERROR)
        console_handler.setFormatter(logging.Formatter('ERROR: %(message)s'))
        logger.addHandler(console_handler)
    
    return logger

class EnhancedProgressTracker:
    """Enhanced progress tracker with detailed metrics."""
    
    def __init__(self, total_files: int):
        self.total_files = total_files
        self.current_index = 0
        self.completed_files = 0
        self.failed_files = 0
        self.skipped_files = 0
        self.start_time = time.time()
        self.file_times = []
        self.current_file_start = None
        self.total_input_size = 0
        self.total_output_size = 0
        self.current_file_progress = 0
        
    def start_file(self, index: int):
        """Mark the start of a file conversion."""
        self.current_index = index
        self.current_file_start = time.time()
        self.current_file_progress = 0
        
    def update_file_progress(self, progress_percent: int):
        """Update current file progress."""
        self.current_file_progress = progress_percent
        
    def complete_file(self, success: bool, skipped: bool = False, input_size: int = 0, output_size: int = 0):
        """Mark the completion of a file conversion."""
        if self.current_file_start is not None:
            duration = time.time() - self.current_file_start
            self.file_times.append(duration)
            # Keep only last 15 times for better ETA calculation
            if len(self.file_times) > 15:
                self.file_times.pop(0)
            
        if skipped:
            self.skipped_files += 1
        elif success:
            self.completed_files += 1
            self.total_input_size += input_size
            self.total_output_size += output_size
        else:
            self.failed_files += 1
            
        self.current_file_progress = 0
    
    def get_processed_count(self) -> int:
        """Get total processed files (completed + failed + skipped)."""
        return self.completed_files + self.failed_files + self.skipped_files
    
    def get_overall_progress_percent(self) -> int:
        """Get overall progress percentage including current file progress."""
        processed = self.get_processed_count()
        if self.total_files == 0:
            return 100
            
        # Add fractional progress for current file
        current_file_fraction = self.current_file_progress / 100.0 if processed < self.total_files else 0
        total_progress = processed + current_file_fraction
        
        return min(100, int((total_progress / self.total_files) * 100))
    
    def get_eta_formatted(self) -> str:
        """Get estimated time remaining in formatted string."""
        if not self.file_times:
            return "calculating..."
            
        processed = self.get_processed_count()
        remaining = self.total_files - processed
        
        if remaining <= 0:
            return "complete"
            
        # Use average of recent conversion times
        avg_time = sum(self.file_times) / len(self.file_times)
        
        # Adjust for current file progress
        current_file_remaining = (100 - self.current_file_progress) / 100.0
        eta_seconds = (remaining - 1 + current_file_remaining) * avg_time
        
        if eta_seconds < 60:
            return f"{int(eta_seconds)}s"
        elif eta_seconds < 3600:
            return f"{int(eta_seconds / 60)}m {int(eta_seconds % 60)}s"
        else:
            hours = int(eta_seconds / 3600)
            minutes = int((eta_seconds % 3600) / 60)
            return f"{hours}h {minutes}m"
    
    def get_elapsed_formatted(self) -> str:
        """Get elapsed time in formatted string."""
        elapsed = time.time() - self.start_time
        if elapsed < 60:
            return f"{int(elapsed)}s"
        elif elapsed < 3600:
            return f"{int(elapsed / 60)}m {int(elapsed % 60)}s"
        else:
            hours = int(elapsed / 3600)
            minutes = int((elapsed % 3600) / 60)
            return f"{hours}h {minutes}m"
    
    def get_processing_rate(self) -> str:
        """Get files processed per hour."""
        elapsed_hours = (time.time() - self.start_time) / 3600
        if elapsed_hours < 0.01:  # Less than 36 seconds
            return "calculating..."
            
        rate = self.get_processed_count() / elapsed_hours
        if rate < 1:
            return f"{rate:.1f}/hr"
        else:
            return f"{int(rate)}/hr"
    
    def get_space_savings(self) -> str:
        """Get total space savings information."""
        if self.total_input_size == 0:
            return "no data yet"
            
        savings_bytes = self.total_input_size - self.total_output_size
        savings_percent = (savings_bytes / self.total_input_size) * 100
        
        def format_size(size_bytes):
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if size_bytes < 1024:
                    return f"{size_bytes:.1f}{unit}"
                size_bytes /= 1024
            return f"{size_bytes:.1f}PB"
        
        if savings_bytes > 0:
            return f"saved {format_size(savings_bytes)} ({savings_percent:+.1f}%)"
        else:
            return f"used {format_size(-savings_bytes)} ({savings_percent:+.1f}%)"

class FFmpegProgressParser:
    """Simple FFmpeg progress parser."""
    
    def __init__(self):
        self.duration_seconds = None
        self.current_seconds = None
        
    def parse_duration(self, line: str):
        """Parse duration from FFmpeg output."""
        if 'Duration:' in line:
            match = re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)', line)
            if match:
                h, m, s = match.groups()
                self.duration_seconds = int(h) * 3600 + int(m) * 60 + float(s)
    
    def parse_progress(self, line: str):
        """Parse current time from FFmpeg output."""
        if 'time=' in line:
            match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', line)
            if match:
                h, m, s = match.groups()
                self.current_seconds = int(h) * 3600 + int(m) * 60 + float(s)
    
    def get_progress_percent(self) -> Optional[int]:
        """Get progress as integer percentage."""
        if self.duration_seconds and self.current_seconds and self.duration_seconds > 0:
            percent = min(100, int((self.current_seconds / self.duration_seconds) * 100))
            return percent
        return None

class VideoConverter:
    def __init__(self, source_dir: str, output_dir: str = None, skip_existing: bool = True):
        """Initialize the video converter."""
        self.source_dir = Path(source_dir).resolve()
        self.output_dir = Path(output_dir).resolve() if output_dir else self.source_dir / "converted"
        self.skip_existing = skip_existing
        self.logger = logging.getLogger(__name__)
        
        # Supported input formats
        self.supported_formats = {'.mp4', '.mkv'}
        
        # FFmpeg settings optimized for quality and size
        self.ffmpeg_args = [
            '-c:v', 'libx264',           # Video codec
            '-preset', 'medium',         # Balanced preset
            '-crf', '23',                # Quality (lower = better, 18-28 range)
            '-c:a', 'aac',               # Audio codec
            '-b:a', '128k',              # Audio bitrate
            '-movflags', '+faststart',   # Optimize for streaming
            '-pix_fmt', 'yuv420p',       # Pixel format for compatibility
            '-threads', '0',             # Use all available CPU threads
        ]
        
    def check_dependencies(self) -> bool:
        """Check if FFmpeg is installed and available."""
        try:
            result = subprocess.run(['ffmpeg', '-version'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                version_line = result.stdout.split('\n')[0]
                self.logger.info(f"FFmpeg found: {version_line}")
                print("* FFmpeg found and ready")
                return True
            else:
                print("X FFmpeg not working properly")
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError):
            print("X FFmpeg not found. Please install FFmpeg: https://ffmpeg.org/download.html")
            return False
        except Exception as e:
            print(f"X Error checking FFmpeg: {e}")
            return False
    
    def find_video_files(self) -> List[Path]:
        """Recursively find all supported video files."""
        print("Scanning for video files...")
        video_files = []
        
        try:
            for root, dirs, files in os.walk(self.source_dir):
                for file in files:
                    file_path = Path(root) / file
                    if file_path.suffix.lower() in self.supported_formats:
                        video_files.append(file_path)
                        
        except Exception as e:
            self.logger.error(f"Error searching for video files: {e}")
            print(f"Error scanning files: {e}")
            
        print(f"* Found {len(video_files)} video files")
        return sorted(video_files)
    
    def get_output_path(self, input_path: Path) -> Path:
        """Generate output path for converted file."""
        rel_path = input_path.relative_to(self.source_dir)
        
        # Generate unique filename if converting .mp4 to .mp4
        if input_path.suffix.lower() == '.mp4':
            output_name = f"{rel_path.stem}_optimized.mp4"
        else:
            output_name = f"{rel_path.stem}.mp4"
            
        output_path = self.output_dir / rel_path.parent / output_name
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        return output_path
    
    def format_file_size(self, size_bytes: int) -> str:
        """Format file size in human readable format."""
        if size_bytes == 0:
            return "0B"
        
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f}{unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f}TB"
    
    def get_file_size(self, file_path: Path) -> int:
        """Get file size in bytes."""
        try:
            return file_path.stat().st_size
        except:
            return 0
    
    def make_progress_bar(self, percent: int, width: int = 30) -> str:
        """Create a simple text-based progress bar."""
        filled = int(width * percent / 100)
        bar = "#" * filled + "-" * (width - filled)
        return f"[{bar}]"
    
    def print_status_header(self, tracker: EnhancedProgressTracker):
        """Print enhanced status header."""
        print("\n" + "="*100)
        print("VIDEO CONVERSION PROGRESS")
        print("="*100)
        
        # Overall progress
        overall_percent = tracker.get_overall_progress_percent()
        progress_bar = self.make_progress_bar(overall_percent, 40)
        print(f"Overall: {progress_bar} {overall_percent}%")
        
        # File statistics
        processed = tracker.get_processed_count()
        print(f"Files: {processed}/{tracker.total_files} | "
              f"Success: {tracker.completed_files} | "
              f"Skipped: {tracker.skipped_files} | "
              f"Failed: {tracker.failed_files}")
        
        # Time and performance info
        elapsed = tracker.get_elapsed_formatted()
        eta = tracker.get_eta_formatted()
        rate = tracker.get_processing_rate()
        
        print(f"Time: {elapsed} elapsed, {eta} remaining | Rate: {rate}")
        
        # Space savings info
        savings = tracker.get_space_savings()
        print(f"Space: {savings}")
        
        print("-" * 100)
        print(f"{'Current File':<35} {'Location':<25} {'Progress':<20} {'Status':<20}")
        print("-" * 100)
    
    def update_status_header(self, tracker: EnhancedProgressTracker):
        """Update the status header in place."""
        # Move cursor up and clear lines
        sys.stdout.write("\033[9A")  # Move up 9 lines
        
        # Clear and rewrite status
        overall_percent = tracker.get_overall_progress_percent()
        progress_bar = self.make_progress_bar(overall_percent, 40)
        sys.stdout.write(f"\033[2KOverall: {progress_bar} {overall_percent}%\n")
        
        processed = tracker.get_processed_count()
        sys.stdout.write(f"\033[2KFiles: {processed}/{tracker.total_files} | "
                        f"Success: {tracker.completed_files} | "
                        f"Skipped: {tracker.skipped_files} | "
                        f"Failed: {tracker.failed_files}\n")
        
        elapsed = tracker.get_elapsed_formatted()
        eta = tracker.get_eta_formatted()
        rate = tracker.get_processing_rate()
        sys.stdout.write(f"\033[2KTime: {elapsed} elapsed, {eta} remaining | Rate: {rate}\n")
        
        savings = tracker.get_space_savings()
        sys.stdout.write(f"\033[2KSpace: {savings}\n")
        
        sys.stdout.write("\033[2K" + "-" * 100 + "\n")
        sys.stdout.write(f"\033[2K{'Current File':<35} {'Location':<25} {'Progress':<20} {'Status':<20}\n")
        sys.stdout.write("\033[2K" + "-" * 100 + "\n")
        
        sys.stdout.flush()
    
    def print_file_progress(self, filename: str, directory: str, progress: str, status: str):
        """Print progress for current file (always updates in place)."""
        # Truncate strings to fit columns
        filename = filename[:32] + "..." if len(filename) > 35 else filename
        directory = directory[:22] + "..." if len(directory) > 25 else directory
        status = status[:17] + "..." if len(status) > 20 else status
        
        # Always update current line (no newlines)
        sys.stdout.write(f"\r{filename:<35} {directory:<25} {progress:<20} {status}")
        # Pad with spaces to clear any remaining characters
        sys.stdout.write(" " * 10)
        sys.stdout.flush()
    
    def convert_video(self, input_path: Path, output_path: Path, file_index: int, tracker: EnhancedProgressTracker) -> Tuple[bool, str]:
        """Convert a single video file."""
        try:
            # Get display info
            filename = input_path.name
            directory = str(input_path.parent.relative_to(self.source_dir))
            if directory == ".":
                directory = "root"
            
            # Skip if output file already exists
            if self.skip_existing and output_path.exists():
                self.print_file_progress(filename, directory, "SKIPPED", "already exists")
                return True, "skipped"
            
            # Get input file size
            input_size = self.get_file_size(input_path)
            input_size_str = self.format_file_size(input_size)
            
            # Build FFmpeg command
            cmd = [
                'ffmpeg', '-i', str(input_path),
                *self.ffmpeg_args,
                '-progress', 'pipe:2',
                '-nostats', '-loglevel', 'error',
                '-y', str(output_path)
            ]
            
            self.logger.debug(f"Converting: {filename}")
            
            # Start conversion process
            parser = FFmpegProgressParser()
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                universal_newlines=True
            )
            
            last_update = 0
            last_header_update = 0
            last_percent = 0
            
            # Monitor progress
            while True:
                line = process.stderr.readline()
                if line == '' and process.poll() is not None:
                    break
                
                if line:
                    parser.parse_duration(line.strip())
                    parser.parse_progress(line.strip())
                    
                    current_time = time.time()
                    
                    # Update file progress every 1 second
                    if current_time - last_update >= 1.0:
                        percent = parser.get_progress_percent()
                        if percent is not None and percent != last_percent:
                            tracker.update_file_progress(percent)
                            
                            # Create file progress bar
                            file_bar = self.make_progress_bar(percent, 15)
                            progress_str = f"{file_bar} {percent}%"
                            status = f"file {file_index}/{tracker.total_files}"
                            
                            self.print_file_progress(filename, directory, progress_str, status)
                            last_percent = percent
                            last_update = current_time
                    
                    # Update header every 3 seconds
                    if current_time - last_header_update >= 3.0:
                        self.update_status_header(tracker)
                        last_header_update = current_time
            
            # Wait for completion
            process.wait()
            
            if process.returncode == 0:
                # Success
                output_size = self.get_file_size(output_path)
                output_size_str = self.format_file_size(output_size)
                
                # Calculate savings
                if input_size > 0:
                    savings = ((input_size - output_size) / input_size) * 100
                    size_info = f"{input_size_str} -> {output_size_str} ({savings:+.1f}%)"
                else:
                    size_info = f"-> {output_size_str}"
                
                self.print_file_progress(filename, directory, "COMPLETE", size_info)
                return True, "success"
            else:
                # Failed
                if output_path.exists():
                    try:
                        output_path.unlink()
                    except:
                        pass
                
                self.print_file_progress(filename, directory, "FAILED", "conversion error")
                return False, "failed"
                
        except Exception as e:
            self.logger.error(f"Error converting {input_path}: {e}")
            self.print_file_progress(filename, directory, "ERROR", str(e)[:17])
            return False, "error"
    
    def convert_all(self) -> dict:
        """Convert all found video files."""
        print("Advanced Video File Converter")
        print(f"Source: {self.source_dir}")
        print(f"Output: {self.output_dir}")
        
        if not self.check_dependencies():
            return {'error': 'FFmpeg not available'}
        
        if not self.source_dir.exists():
            print(f"Error: Source directory does not exist")
            return {'error': 'Source directory not found'}
        
        # Find all video files
        video_files = self.find_video_files()
        
        if not video_files:
            print("No video files found to convert")
            return {'total': 0, 'success': 0, 'failed': 0, 'skipped': 0}
        
        # Initialize progress tracking
        tracker = EnhancedProgressTracker(len(video_files))
        
        # Statistics
        stats = {'total': len(video_files), 'success': 0, 'failed': 0, 'skipped': 0}
        failed_files = []
        
        # Print initial status
        self.print_status_header(tracker)
        
        # Process each file
        for i, input_path in enumerate(video_files, 1):
            try:
                output_path = self.get_output_path(input_path)
                tracker.start_file(i)
                
                success, result_type = self.convert_video(input_path, output_path, i, tracker)
                
                # Get file sizes for tracking
                input_size = self.get_file_size(input_path)
                output_size = self.get_file_size(output_path) if success and result_type != "skipped" else 0
                
                tracker.complete_file(success, result_type == "skipped", input_size, output_size)
                
                # Update statistics
                if result_type == "skipped":
                    stats['skipped'] += 1
                elif success:
                    stats['success'] += 1
                else:
                    stats['failed'] += 1
                    failed_files.append(str(input_path))
                
                # Update header after each file
                self.update_status_header(tracker)
                    
            except KeyboardInterrupt:
                print(f"\n\nConversion interrupted by user!")
                print(f"Processed: {i-1}/{len(video_files)} files")
                break
            except Exception as e:
                self.logger.error(f"Unexpected error processing {input_path}: {e}")
                stats['failed'] += 1
                failed_files.append(str(input_path))
                tracker.complete_file(False, False)
        
        # Final summary
        print("\n\n" + "="*100)
        elapsed = tracker.get_elapsed_formatted()
        savings = tracker.get_space_savings()
        print(f"CONVERSION COMPLETE! Total time: {elapsed}")
        print(f"Results: {stats['success']} successful, {stats['skipped']} skipped, {stats['failed']} failed")
        print(f"Space savings: {savings}")
        
        if failed_files:
            print(f"\nFailed files ({len(failed_files)}):")
            for i, failed_file in enumerate(failed_files[:5]):  # Show first 5
                print(f"  {i+1}. {Path(failed_file).name}")
            if len(failed_files) > 5:
                print(f"  ... and {len(failed_files) - 5} more (check log file)")
        
        stats['failed_files'] = failed_files
        return stats

def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Advanced Video File Converter")
    
    parser.add_argument('source_dir', help='Directory to search for video files')
    parser.add_argument('-o', '--output-dir', help='Output directory (default: source_dir/converted)')
    parser.add_argument('--no-skip-existing', action='store_true', help='Re-convert existing files')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose logging')
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logging(args.verbose)
    
    # Validate source directory
    source_path = Path(args.source_dir)
    if not source_path.exists():
        print(f"Error: Source directory not found: {args.source_dir}")
        sys.exit(1)
    
    # Create converter instance
    converter = VideoConverter(
        source_dir=args.source_dir,
        output_dir=args.output_dir,
        skip_existing=not args.no_skip_existing
    )
    
    try:
        # Run conversion
        stats = converter.convert_all()
        
        if 'error' in stats:
            print(f"Error: {stats['error']}")
            sys.exit(1)
        
        # Exit with error code if conversions failed
        if stats['failed'] > 0:
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        print(f"Unexpected error occurred. Check log file for details.")
        sys.exit(1)

if __name__ == "__main__":
    main()
