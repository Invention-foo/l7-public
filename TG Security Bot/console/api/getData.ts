import { createServerSupabaseClient } from '../../lib/supabase-server'

export async function getData() {
  const supabase = await createServerSupabaseClient()
  const { data, error } = await supabase
    .from('your_table')
    .select('*')

  if (error) throw error
  return data
}