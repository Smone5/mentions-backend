-- Migration 006: Add status and approval tracking fields to drafts table
-- This aligns the drafts table with the backend API expectations

-- Add status column to drafts
ALTER TABLE drafts 
ADD COLUMN status text CHECK (status IN ('pending', 'approved', 'rejected', 'posted', 'failed')) DEFAULT 'pending';

-- Add approval tracking fields
ALTER TABLE drafts
ADD COLUMN approved_by uuid REFERENCES auth.users(id),
ADD COLUMN approved_at timestamptz,
ADD COLUMN rejected_by uuid REFERENCES auth.users(id),
ADD COLUMN rejected_at timestamptz,
ADD COLUMN rejection_reason text,
ADD COLUMN edited_by uuid REFERENCES auth.users(id),
ADD COLUMN updated_at timestamptz;

-- Rename text column to body for consistency with API
ALTER TABLE drafts RENAME COLUMN text TO body;

-- Add indexes for common queries
CREATE INDEX idx_drafts_status ON drafts(status);
CREATE INDEX idx_drafts_approved ON drafts(approved_by, approved_at DESC) WHERE approved_by IS NOT NULL;
CREATE INDEX idx_drafts_artifact_status ON drafts(artifact_id, status);

-- Update existing drafts to have pending status
UPDATE drafts SET status = 'pending' WHERE status IS NULL;

