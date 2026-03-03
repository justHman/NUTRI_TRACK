from ultralytics import SAM
from ultralytics.models.sam import SAM3SemanticPredictor
from ultralytics.utils.plotting import Annotator, colors
import torch
import os

class SAM3Segmenter:
    """SAM3 with Ultralytics - Full feature support
    
    Supports:
    - Text prompts: segment_text(["rice", "meat"])
    - Point prompts: segment_point([x, y])
    - Box prompts: segment_box([x1, y1, x2, y2])
    - Exemplar prompts: segment_exemplar([[x1, y1, x2, y2]])
    """
    def __init__(self, model_path=None, conf=0.25):
        # Default weight path relative to app/ root
        if model_path is None:
            app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            model_path = os.path.join(app_root, "data", "weights", "sam3.pt")
            
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        print(f"🔄 Loading SAM3 from {model_path} on {self.device.upper()}...")
        self.model_path = model_path
        self.conf = conf
        
        # For visual prompts (point/box)
        self.sam = SAM(model_path).to(self.device)
        
        # For semantic/text prompts
        self.semantic_overrides = dict(
            conf=conf,
            task="segment",
            mode="predict",
            model=model_path,
            half=True if self.device == 'cuda' else False, # Half precision only on GPU
            verbose=False,
            device=self.device
        )
        self.semantic_predictor = SAM3SemanticPredictor(overrides=self.semantic_overrides)
        self.current_image = None
        print(f"✅ SAM3 Ready on {self.device.upper()}!")
    
    def set_image(self, image_path):
        """Set image for semantic queries (reuse features)"""
        self.current_image = image_path
        self.semantic_predictor.set_image(image_path)
    
    def segment_text(self, texts, image_path=None):
        """Segment by text description
        
        Args:
            texts: List of text prompts, e.g. ["rice", "meat", "vegetable"]
            image_path: Path to image (optional if set_image called)
        """
        if image_path:
            self.set_image(image_path)
        results = self.semantic_predictor(text=texts)
        return results
    
    def segment_exemplar(self, bboxes, image_path=None):
        """Segment using bounding box exemplars (find similar objects)
        
        Args:
            bboxes: List of [x1, y1, x2, y2] boxes as examples
            image_path: Path to image (optional if set_image called)
        """
        if image_path:
            self.set_image(image_path)
        results = self.semantic_predictor(bboxes=bboxes)
        return results
    
    def segment_point(self, points, labels=None, image_path=None):
        """Segment by point clicks (SAM2 compatible)
        
        Args:
            points: Single point [x, y] or multiple [[x1, y1], [x2, y2]]
            labels: 1 for foreground, 0 for background
            image_path: Path to image
        """
        if image_path is None:
            image_path = self.current_image
        if labels is None:
            labels = [1] * (len(points) if isinstance(points[0], list) else 1)
        results = self.sam.predict(source=image_path, points=points, labels=labels)
        return results
    
    def segment_box(self, bbox, image_path=None):
        """Segment by bounding box (SAM2 compatible)
        
        Args:
            bbox: [x1, y1, x2, y2]
            image_path: Path to image
        """
        if image_path is None:
            image_path = self.current_image
        results = self.sam.predict(source=image_path, bboxes=bbox)
        return results
    
    def show_results(self, results):
        """Display segmentation results"""
        for r in results:
            r.show()
    
    def unload(self):
        del self.sam, self.semantic_predictor
        torch.cuda.empty_cache() if torch.cuda.is_available() else None

if __name__ == "__main__":
    segmenter = SAM3Segmenter()
    test_img = r"data\images\food\fast_food.jpg"
    segmenter.set_image(test_img)
    segmenter.show_results(segmenter.segment_text(["rice", "meat", "vegetable"]))
