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
- `{weighted_rating}`: Weighted rating (format: "rating_X.X") that combines the model's rating with its download count using logarithmic scaling. For example, "rating_4.5". This provides a balanced metric that considers both the quality (rating) and popularity (downloads) of the model.

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
