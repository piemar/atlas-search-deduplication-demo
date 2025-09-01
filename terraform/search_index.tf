resource "mongodbatlas_search_index" "deduplication_index" {
  project_id   = var.project_id
  cluster_name = var.cluster_name
  database     = "dedup_demo"
  collection   = "consumers"
  name         = "dedup_index"

  mappings_dynamic = true

  mappings = jsonencode({
    dynamic = true,
    fields = {
      first_name = {
        type           = "string",
        analyzer       = "lucene.standard",
        searchAnalyzer = "lucene.standard"
      },
      last_name = {
        type           = "string",
        analyzer       = "lucene.standard",
        searchAnalyzer = "lucene.standard"
      },
      email = {
        type     = "string",
        analyzer = "lucene.keyword"
      },
      phone = {
        type     = "string",
        analyzer = "lucene.keyword"
      },
      address = {
        type     = "string",
        analyzer = "lucene.english"
      }
    }
  })
}