"""
Data models for CivitAI API responses.

This module defines dataclasses for the various API responses from CivitAI.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime


@dataclass
class Creator:
    """Creator information."""
    
    username: str
    image: Optional[str] = None


@dataclass
class Stats:
    """Model statistics."""
    
    download_count: int
    favorite_count: int
    comment_count: int
    rating_count: int
    rating: float


@dataclass
class FileMetadata:
    """Model file metadata."""
    
    fp: Optional[str] = None
    size: Optional[str] = None
    format: Optional[str] = None


@dataclass
class ModelFile:
    """Model file information."""
    
    name: str
    id: str
    size_kb: int
    type: str
    metadata: Optional[FileMetadata] = None
    pickle_scan_result: Optional[str] = None
    virus_scan_result: Optional[str] = None
    scanned_at: Optional[datetime] = None
    primary: bool = False


@dataclass
class ImageMeta:
    """Image generation metadata."""
    
    prompt: Optional[str] = None
    negative_prompt: Optional[str] = None
    sampler: Optional[str] = None
    cfg_scale: Optional[float] = None
    steps: Optional[int] = None
    seed: Optional[int] = None
    model: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ImageMeta':
        """
        Create ImageMeta from dictionary.
        
        Args:
            data: Dictionary containing image metadata
            
        Returns:
            ImageMeta instance
        """
        return cls(
            prompt=data.get("prompt"),
            negative_prompt=data.get("negativePrompt"),
            sampler=data.get("sampler"),
            cfg_scale=data.get("cfgScale"),
            steps=data.get("steps"),
            seed=data.get("seed"),
            model=data.get("model"),
        )


@dataclass
class Image:
    """Model image information."""
    
    id: str
    url: str
    nsfw: bool
    width: int
    height: int
    hash: Optional[str] = None
    meta: Optional[ImageMeta] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Image':
        """
        Create Image from dictionary.
        
        Args:
            data: Dictionary containing image data
            
        Returns:
            Image instance
        """
        meta = None
        if data.get("meta"):
            meta = ImageMeta.from_dict(data["meta"])
        
        return cls(
            id=data["id"],
            url=data["url"],
            nsfw=data["nsfw"],
            width=data["width"],
            height=data["height"],
            hash=data.get("hash"),
            meta=meta,
        )


@dataclass
class ModelVersion:
    """Model version information."""
    
    id: int
    name: str
    created_at: datetime
    download_url: str
    description: Optional[str] = None
    trained_words: List[str] = field(default_factory=list)
    files: List[ModelFile] = field(default_factory=list)
    images: List[Image] = field(default_factory=list)
    stats: Optional[Stats] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ModelVersion':
        """
        Create ModelVersion from dictionary.
        
        Args:
            data: Dictionary containing model version data
            
        Returns:
            ModelVersion instance
        """
        # Parse created_at
        created_at = datetime.fromisoformat(data["createdAt"].replace("Z", "+00:00"))
        
        # Parse files
        files = []
        for file_data in data.get("files", []):
            metadata = None
            if file_data.get("metadata"):
                metadata = FileMetadata(
                    fp=file_data["metadata"].get("fp"),
                    size=file_data["metadata"].get("size"),
                    format=file_data["metadata"].get("format"),
                )
            
            scanned_at = None
            if file_data.get("scannedAt"):
                scanned_at = datetime.fromisoformat(file_data["scannedAt"].replace("Z", "+00:00"))
            
            files.append(ModelFile(
                name=file_data.get("name", ""),
                id=file_data.get("id", ""),
                size_kb=file_data.get("sizeKb", 0),
                type=file_data.get("type", ""),
                metadata=metadata,
                pickle_scan_result=file_data.get("pickleScanResult"),
                virus_scan_result=file_data.get("virusScanResult"),
                scanned_at=scanned_at,
                primary=file_data.get("primary", False),
            ))
        
        # Parse images
        images = []
        for image_data in data.get("images", []):
            images.append(Image.from_dict(image_data))
        
        # Parse stats
        stats = None
        if data.get("stats"):
            stats = Stats(
                download_count=data["stats"].get("downloadCount", 0),
                favorite_count=data["stats"].get("favoriteCount", 0),
                comment_count=data["stats"].get("commentCount", 0),
                rating_count=data["stats"].get("ratingCount", 0),
                rating=data["stats"].get("rating", 0.0),
            )
        
        return cls(
            id=data["id"],
            name=data["name"],
            created_at=created_at,
            download_url=data["downloadUrl"],
            description=data.get("description"),
            trained_words=data.get("trainedWords", []),
            files=files,
            images=images,
            stats=stats,
        )


@dataclass
class Model:
    """Model information."""
    
    id: int
    name: str
    type: str
    nsfw: bool
    description: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    creator: Optional[Creator] = None
    stats: Optional[Stats] = None
    model_versions: List[ModelVersion] = field(default_factory=list)
    mode: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Model':
        """
        Create Model from dictionary.
        
        Args:
            data: Dictionary containing model data
            
        Returns:
            Model instance
        """
        # Parse creator
        creator = None
        if data.get("creator"):
            creator = Creator(
                username=data["creator"]["username"],
                image=data["creator"].get("image"),
            )
        
        # Parse stats
        stats = None
        if data.get("stats"):
            stats = Stats(
                download_count=data["stats"].get("downloadCount", 0),
                favorite_count=data["stats"].get("favoriteCount", 0),
                comment_count=data["stats"].get("commentCount", 0),
                rating_count=data["stats"].get("ratingCount", 0),
                rating=data["stats"].get("rating", 0.0),
            )
        
        # Parse model versions
        model_versions = []
        for version_data in data.get("modelVersions", []):
            model_versions.append(ModelVersion.from_dict(version_data))
        
        return cls(
            id=data["id"],
            name=data["name"],
            type=data["type"],
            nsfw=data["nsfw"],
            description=data.get("description"),
            tags=data.get("tags", []),
            creator=creator,
            stats=stats,
            model_versions=model_versions,
            mode=data.get("mode"),
        )


@dataclass
class SearchResult:
    """Search result."""
    
    items: List[Model]
    metadata: Dict[str, Any]
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SearchResult':
        """
        Create SearchResult from dictionary.
        
        Args:
            data: Dictionary containing search result data
            
        Returns:
            SearchResult instance
        """
        items = []
        for item_data in data.get("items", []):
            items.append(Model.from_dict(item_data))
        
        return cls(
            items=items,
            metadata=data.get("metadata", {}),
        )


@dataclass
class ImageSearchResult:
    """Image search result."""
    
    items: List[Image]
    metadata: Dict[str, Any]
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ImageSearchResult':
        """
        Create ImageSearchResult from dictionary.
        
        Args:
            data: Dictionary containing image search result data
            
        Returns:
            ImageSearchResult instance
        """
        items = []
        for item_data in data.get("items", []):
            items.append(Image.from_dict(item_data))
        
        return cls(
            items=items,
            metadata=data.get("metadata", {}),
        )
