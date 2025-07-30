from typing import Any, List
import io
import time
import hashlib
import requests
from PIL import Image

from griptape_nodes.exe_types.node_types import DataNode, NodeResolutionState
from griptape_nodes.exe_types.core_types import Parameter, ParameterMode, ParameterTypeBuiltin
from griptape.artifacts import ImageArtifact, ImageUrlArtifact
from griptape_nodes.exe_types.node_types import BaseNode
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes
from griptape_nodes.traits.options import Options


class StoryboardImageNode(DataNode):
    def __init__(self, name: str, metadata: dict[Any, Any] | None = None) -> None:
        super().__init__(name, metadata)
        
        # Input parameter for list of images
        self.add_parameter(
            Parameter(
                name="images",
                tooltip="List of images to arrange in a grid",
                type="list",
                input_types=["list"],
                allowed_modes={ParameterMode.INPUT},
                ui_options={
                    "display_name": "Images",
                }
            )
        )
        
        # Background color parameter
        self.add_parameter(
            Parameter(
                name="background_color",
                tooltip="Background color for the storyboard grid (hex format, e.g., #000000)",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value="#000000",
                ui_options={
                    "display_name": "Background Color",
                    "placeholder_text": "#000000"
                }
            )
        )

        # Grid layout parameters
        self.add_parameter(
            Parameter(
                name="columns",
                tooltip="Number of columns in the grid",
                type=ParameterTypeBuiltin.INT.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value=3,
                ui_options={
                    "display_name": "Columns"
                }
            )
        )

        self.add_parameter(
            Parameter(
                name="padding",
                tooltip="Padding between images (in pixels)",
                type=ParameterTypeBuiltin.INT.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value=10,
                ui_options={
                    "display_name": "Padding"
                }
            )
        )
        
        # Output image size parameter
        self.add_parameter(
            Parameter(
                name="output_image_size",
                tooltip="Size and aspect ratio of the output storyboard image",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                default_value="1920x1080",
                traits={Options(choices=["4k (3840x2160)", "1440p (2560x1440)", "1080p (1920x1080)", "720p (1280x720)"])},
                ui_options={
                    "display_name": "Output Image Size"
                }
            )
        )
        
        # Output parameter for the storyboard image
        self.add_parameter(
            Parameter(
                name="storyboard_output",
                tooltip="Generated storyboard grid image",
                output_type="ImageUrlArtifact",
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={
                    "display_name": "Storyboard Output",
                    "is_full_width": True,
                    "pulse_on_run": True
                }
            )
        )
        
        # Status message parameter
        self.add_parameter(
            Parameter(
                name="status_message",
                tooltip="Status messages about the storyboard creation process",
                type=ParameterTypeBuiltin.STR.value,
                allowed_modes={ParameterMode.PROPERTY},
                ui_options={
                    "multiline": True,
                    "hide": False
                }
            )
        )

    def process(self) -> None:
        """Process the images and create a storyboard grid."""
        images_list = self.get_parameter_value("images")
        bg_color = self.get_parameter_value("background_color")
        columns = self.get_parameter_value("columns")
        padding = self.get_parameter_value("padding")
        output_image_size = self.get_parameter_value("output_image_size")
        
        if not images_list or not isinstance(images_list, list) or len(images_list) == 0:
            self.parameter_values["status_message"] = "No images provided or invalid input"
            return

        try:
            # Process the list of images
            pil_images = []
            for img_item in images_list:
                if isinstance(img_item, ImageArtifact):
                    # If it's already an ImageArtifact
                    img_bytes = img_item.to_bytes()
                    pil_img = Image.open(io.BytesIO(img_bytes))
                    pil_images.append(pil_img)
                elif isinstance(img_item, ImageUrlArtifact):
                    # If it's an ImageUrlArtifact
                    response = requests.get(img_item.value, timeout=30)
                    response.raise_for_status()
                    pil_img = Image.open(io.BytesIO(response.content))
                    pil_images.append(pil_img)
                elif isinstance(img_item, dict) and "url" in img_item:
                    # If it's a dict with a URL, we'd need to fetch it
                    self.parameter_values["status_message"] = "URL-based images not yet supported"
                    return
                elif isinstance(img_item, bytes):
                    # If it's raw bytes
                    pil_img = Image.open(io.BytesIO(img_item))
                    pil_images.append(pil_img)
                else:
                    self.parameter_values["status_message"] = f"Unsupported image format: {type(img_item)}"
                    return

            # Get target output size first
            target_size = self._parse_output_size(output_image_size) or (1920, 1080)
            
            # Create the storyboard grid (this creates a storyboard with the right aspect ratio based on images)
            storyboard = self.create_storyboard_grid(
                pil_images, 
                bg_color, 
                columns, 
                padding, 
                target_size
            )
            
            # Convert to ImageUrlArtifact using StaticFilesManager
            buffer = io.BytesIO()
            storyboard.save(buffer, format="PNG")
            
            # Generate a unique filename for the image
            timestamp = int(time.time() * 1000)
            content_hash = hashlib.md5(buffer.getvalue()).hexdigest()[:8]
            filename = f"storyboard_{timestamp}_{content_hash}.png"
            
            # Save image using StaticFilesManager and get URL
            static_files_manager = GriptapeNodes.StaticFilesManager()
            static_url = static_files_manager.save_static_file(buffer.getvalue(), filename)
            
            # Create ImageUrlArtifact with the URL
            image_url_artifact = ImageUrlArtifact(value=static_url, name=f"storyboard_{timestamp}")
            
            # Set the output
            self.parameter_output_values["storyboard_output"] = image_url_artifact
            self.parameter_values["status_message"] = "Storyboard generated successfully"

        except Exception as e:
            self.parameter_values["status_message"] = f"Error generating storyboard: {str(e)}"
            raise

    def create_storyboard_grid(self, images: List[Image.Image], bg_color: str, columns: int, padding: int, target_size: tuple[int, int]) -> Image.Image:
        """Create a grid layout from the provided images and resize to target dimensions."""
        if not images:
            raise ValueError("No images provided")
            
        # Parse background color
        try:
            # Handle hex color
            if bg_color.startswith('#'):
                r = int(bg_color[1:3], 16)
                g = int(bg_color[3:5], 16)
                b = int(bg_color[5:7], 16)
                bg_color_tuple = (r, g, b)
            else:
                # Default to black if parsing fails
                bg_color_tuple = (0, 0, 0)
        except Exception:
            bg_color_tuple = (0, 0, 0)
            
        # Ensure columns is valid
        if not isinstance(columns, int) or columns < 1:
            columns = 3
            
        # Calculate rows needed
        num_images = len(images)
        rows = (num_images + columns - 1) // columns  # Ceiling division
        
        # Get target dimensions
        target_width, target_height = target_size
        
        # Determine individual image size based on target dimensions
        # Calculate the maximum size each image can be to fit within the target dimensions
        available_width = (target_width - (columns + 1) * padding) // columns
        max_rows = (num_images + columns - 1) // columns  # Ceiling division to get number of rows
        available_height = (target_height - (max_rows + 1) * padding) // max_rows
        
        # Resize all images to fit within the calculated dimensions
        resized_images = []
        for img in images:
            # Maintain aspect ratio
            img_width, img_height = img.size
            aspect_ratio = img_width / img_height
            
            if aspect_ratio > 1:  # Wider than tall
                new_width = available_width
                new_height = int(new_width / aspect_ratio)
                if new_height > available_height:
                    new_height = available_height
                    new_width = int(new_height * aspect_ratio)
            else:  # Taller than wide or square
                new_height = available_height
                new_width = int(new_height * aspect_ratio)
                if new_width > available_width:
                    new_width = available_width
                    new_height = int(new_width / aspect_ratio)
                    
            resized_img = img.resize((new_width, new_height), Image.LANCZOS)
            resized_images.append(resized_img)
            
        # Create the canvas with the exact target dimensions
        final_image = Image.new('RGB', target_size, color=bg_color_tuple)
        
        # Calculate layout for placing images on the canvas
        base_width = resized_images[0].width if resized_images else available_width
        base_height = resized_images[0].height if resized_images else available_height
        
        # Calculate actual grid dimensions based on the resized images
        grid_width = columns * base_width + (columns + 1) * padding
        grid_height = rows * base_height + (rows + 1) * padding
        
        # Create a grid image for the resized images
        grid_image = Image.new('RGB', (grid_width, grid_height), color=bg_color_tuple)
        
        # Calculate center offset to center the grid 
        # (not needed for full rows, but applies to the last row if it's not full)
        last_row_items = num_images % columns
        if last_row_items == 0:
            last_row_items = columns  # Last row is full
        
        # Place each image in the grid
        for idx, img in enumerate(resized_images):
            row = idx // columns
            col = idx % columns
            
            # Center the items in the last row if it's not a full row
            if row == rows - 1 and last_row_items < columns:
                # Calculate centering offset for the last row
                offset = (columns - last_row_items) * (base_width + padding) // 2
                x = col * (base_width + padding) + padding + offset
            else:
                # Normal grid placement
                x = col * (base_width + padding) + padding
                
            y = row * (base_height + padding) + padding
            grid_image.paste(img, (x, y))
            
        # Center the grid on the final canvas
        paste_x = max(0, (target_width - grid_width) // 2)
        paste_y = max(0, (target_height - grid_height) // 2)
        final_image.paste(grid_image, (paste_x, paste_y))
            
        return final_image

    def mark_for_processing(self) -> None:
        """Mark this node as needing to be processed."""
        # Reset the node's state to UNRESOLVED
        self.state = NodeResolutionState.UNRESOLVED
        
        # Clear any existing output values
        for param in self.parameters:
            if ParameterMode.OUTPUT in param.allowed_modes:
                self.parameter_output_values[param.name] = None

    def after_value_set(self, parameter: Parameter, value: Any) -> None:
        # If this parameter change requires reprocessing
        if parameter.name in ["images", "background_color", "columns", "padding", "output_image_size"]:
            self.mark_for_processing()

    def after_incoming_connection(
        self,
        source_node: BaseNode,  # noqa: ARG002
        source_parameter: Parameter,  # noqa: ARG002
        target_parameter: Parameter,
    ) -> None:
        """Callback after a Connection has been established TO this Node."""
        # Mark for processing when we get a new input connection
        if target_parameter.name in ["images", "background_color", "columns", "padding", "output_image_size"]:
            self.mark_for_processing()

    def after_incoming_connection_removed(
        self,
        source_node: BaseNode,  # noqa: ARG002
        source_parameter: Parameter,  # noqa: ARG002
        target_parameter: Parameter,
    ) -> None:
        """Callback after a Connection TO this Node was REMOVED."""
        # Mark for processing when an input connection is removed
        if target_parameter.name in ["images", "background_color", "columns", "padding", "output_image_size"]:
            self.mark_for_processing()
            # Clear the parameter value since the connection was removed
            self.remove_parameter_value(target_parameter.name)

    def validate_before_workflow_run(self) -> list[Exception] | None:
        """Validate the node configuration before running."""
        exceptions = []
        images = self.get_parameter_value("images")
        
        if not images or not isinstance(images, list) or len(images) == 0:
            exceptions.append(ValueError("No images provided or invalid input"))
            
        return exceptions if exceptions else None
        
    def _parse_output_size(self, output_size: str) -> tuple[int, int] | None:
        """Parse the output size parameter into a tuple of width and height."""
        # Define a mapping of options to actual resolutions
        size_map = {
            "4k (3840x2160)": (3840, 2160),
            "1920x1080": (1920, 1080),
            "1440p (2560x1440)": (2560, 1440),
            "720p (1280x720)": (1280, 720)
        }
        
        # Return the mapped value or None if not found
        return size_map.get(output_size)
        
