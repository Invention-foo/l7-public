'use server'

import { createServerSupabaseClient } from '@/lib/supabase-server'

export async function updateSetting(settingsId: string, settingName: string, value: boolean) {
  const supabase = await createServerSupabaseClient()
  
  const { error } = await supabase
    .from('athena_secure_settings')
    .update({ [settingName]: value })
    .eq('id', settingsId)

  if (error) throw error
} 