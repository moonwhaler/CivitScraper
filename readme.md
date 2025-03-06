# CivitScraper - make it local again.

[Previous content from original readme up to Custom Organization Templates section remains exactly the same...]

### Custom Organization Templates

You can create custom organization templates using the `custom_template` setting:

```yaml
organization:
  custom_template: "{type}/{creator}/{base_model}"
```

Available placeholders:
- `{model_name}`: Model name
- `{model_type}`: Model type
- `{type}`: Model type (alias for model_type)
- `{creator}`: Creator username
- `{base_model}`: Base model
- `{nsfw}`: NSFW status (nsfw/sfw)
- `{year}`: Creation year
- `{month}`: Creation month
- `{weighted_rating}`: Confidence-adjusted rating (1-5) that considers both rating value and rating count vs downloads
- `{weighted_thumbsup}`: Normalized thumbs up rating (1-5) based on thumbs up to download ratio

### Rating System

CivitScraper provides two weighted rating metrics to help evaluate models:

1. Weighted Rating (1-5):
   - Adjusts the model's rating based on rating count vs download count
   - Low rating count relative to downloads reduces confidence
   - Rating pulls toward neutral (3.0) when confidence is low
   - Full rating value preserved when confidence is high (20%+ ratio)

2. Weighted Thumbs Up (1-5):
   - Based on the ratio of thumbs up to downloads
   - Uses 20% steps for clear categorization:
     * 0% thumbs up = 1.0 rating
     * 20%+ thumbs up = 5.0 rating
     * Linear scale between 0-20%

Available organization templates:
- `by_type`: Organize by model type
- `by_creator`: Organize by creator
- `by_type_and_creator`: Organize by type and creator
- `by_type_and_basemodel`: Organize by type and base model
- `by_base_model`: Organize by base model and type
- `by_nsfw`: Organize by NSFW status and type
- `by_type_basemodel_nsfw`: Organize by type, base model, and NSFW status
- `by_date`: Organize by year, month, and type
- `by_model_info`: Organize by model type and name
- `by_rating`: Organize by weighted rating and type
- `by_type_and_rating`: Organize by type and weighted rating

The organization system intelligently creates the directory structure and formats file paths using these placeholders, ensuring a consistent and logical organization scheme.

[All remaining content from original readme exactly as it was...]
