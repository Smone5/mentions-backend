-- Migration: Add owner_id to companies table
-- Description: Adds owner relationship to companies for proper RLS policies
-- Date: 2024

-- Add owner_id column to companies table
ALTER TABLE companies
ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES user_profiles(id) ON DELETE SET NULL;

-- Create index for owner lookups
CREATE INDEX IF NOT EXISTS idx_companies_owner ON companies(owner_id);

-- Drop existing policies if they exist (from failed migration 002)
DROP POLICY IF EXISTS "Users can view own company" ON companies;
DROP POLICY IF EXISTS "Owners can update company" ON companies;

-- Create RLS policies for companies
-- Users can read companies they own or are associated with
CREATE POLICY "Users can view own company"
    ON companies FOR SELECT
    USING (
        owner_id = auth.uid() OR
        id IN (SELECT company_id FROM user_profiles WHERE id = auth.uid())
    );

-- Company owners can update their company
CREATE POLICY "Owners can update company"
    ON companies FOR UPDATE
    USING (owner_id = auth.uid());

-- Company owners can delete their company
CREATE POLICY "Owners can delete company"
    ON companies FOR DELETE
    USING (owner_id = auth.uid());

-- Comment for documentation
COMMENT ON COLUMN companies.owner_id IS 'User who owns/created this company';





