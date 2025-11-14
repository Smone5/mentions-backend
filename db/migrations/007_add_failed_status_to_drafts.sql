-- Migration 007: Add 'failed' status to drafts table
-- Fixes the issue where posting failures couldn't update draft status

-- Drop the existing check constraint
ALTER TABLE drafts 
DROP CONSTRAINT IF EXISTS drafts_status_check;

-- Add the updated check constraint with 'failed' status
ALTER TABLE drafts 
ADD CONSTRAINT drafts_status_check 
CHECK (status IN ('pending', 'approved', 'rejected', 'posted', 'failed'));

