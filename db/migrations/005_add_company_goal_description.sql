-- Migration 005: Add goal and description to companies table
-- Description: Adds goal and description fields to companies for better context
-- Date: 2024-11-07

-- Add goal and description columns to companies table
ALTER TABLE companies
ADD COLUMN IF NOT EXISTS goal TEXT,
ADD COLUMN IF NOT EXISTS description TEXT;

-- Add comments for documentation
COMMENT ON COLUMN companies.goal IS 'Company goal or mission statement used for AI context';
COMMENT ON COLUMN companies.description IS 'Detailed company description';

