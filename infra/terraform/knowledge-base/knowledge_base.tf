resource "aws_iam_role" "kb" {
  name = "${var.name}-kb"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "bedrock.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = local.account_id }
        ArnLike      = { "aws:SourceArn" = "arn:${local.partition}:bedrock:${local.region}:${local.account_id}:knowledge-base/*" }
      }
    }]
  })
}

# Scoped access: one embedding model, one bucket (read), one vector index, two keys.
resource "aws_iam_role_policy" "kb" {
  name = "knowledge-base"
  role = aws_iam_role.kb.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EmbedWithOneModel"
        Effect   = "Allow"
        Action   = "bedrock:InvokeModel"
        Resource = local.embedding_model_arn
      },
      {
        Sid       = "ListPolicyBucket"
        Effect    = "Allow"
        Action    = "s3:ListBucket"
        Resource  = var.policies_bucket_arn
        Condition = { StringEquals = { "aws:ResourceAccount" = local.account_id } }
      },
      {
        Sid       = "ReadPolicyDocuments"
        Effect    = "Allow"
        Action    = "s3:GetObject"
        Resource  = "${var.policies_bucket_arn}/*"
        Condition = { StringEquals = { "aws:ResourceAccount" = local.account_id } }
      },
      {
        Sid    = "WriteAndQueryOneIndex"
        Effect = "Allow"
        Action = [
          "s3vectors:GetIndex", "s3vectors:PutVectors", "s3vectors:GetVectors", "s3vectors:DeleteVectors",
          "s3vectors:QueryVectors", "s3vectors:ListVectors",
        ]
        Resource = aws_s3vectors_index.policies.index_arn
      },
      {
        Sid      = "DecryptDocuments"
        Effect   = "Allow"
        Action   = "kms:Decrypt"
        Resource = var.data_kms_key_arn
      },
      {
        Sid      = "EncryptVectorsAndIngestionData"
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = aws_kms_key.kb.arn
      },
    ]
  })
}

resource "aws_bedrockagent_knowledge_base" "this" {
  name        = "${var.name}-policies"
  description = "Harbor Goods store, warranty, shipping and supplier policies"
  role_arn    = aws_iam_role.kb.arn

  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = local.embedding_model_arn
      embedding_model_configuration {
        bedrock_embedding_model_configuration {
          dimensions          = var.embedding_dimensions
          embedding_data_type = "FLOAT32"
        }
      }
    }
  }

  storage_configuration {
    type = "S3_VECTORS"
    s3_vectors_configuration {
      index_arn = aws_s3vectors_index.policies.index_arn
    }
  }

  depends_on = [aws_iam_role_policy.kb]
}

resource "aws_bedrockagent_data_source" "policies" {
  name                 = "policies"
  knowledge_base_id    = aws_bedrockagent_knowledge_base.this.id
  data_deletion_policy = "DELETE"

  data_source_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn              = var.policies_bucket_arn
      bucket_owner_account_id = local.account_id
    }
  }

  server_side_encryption_configuration {
    kms_key_arn = aws_kms_key.kb.arn
  }

  vector_ingestion_configuration {
    chunking_configuration {
      chunking_strategy = "FIXED_SIZE"
      fixed_size_chunking_configuration {
        max_tokens         = var.chunk_max_tokens
        overlap_percentage = var.chunk_overlap_percentage
      }
    }
  }
}
