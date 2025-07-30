import { NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || '';
const supabaseServiceKey = process.env.SUPABASE_SERVICE_ROLE_KEY || '';
const supabaseAdmin = createClient(supabaseUrl, supabaseServiceKey);

export async function POST(request: Request) {
  try {
    const { userIds } = await request.json();
    
    console.log('API: Checking blacklist status for user IDs:', userIds)
    
    if (!supabaseUrl || !supabaseServiceKey) {
      console.error('API: Missing Supabase configuration')
      return NextResponse.json({ 
        success: false, 
        message: "Server configuration error" 
      }, { status: 500 });
    }
    
    if (!userIds || !Array.isArray(userIds) || userIds.length === 0) {
      return NextResponse.json({
        success: true,
        data: []
      });
    }
    
    // Query only for the specific user IDs
    const { data: blacklistedUsers, error } = await supabaseAdmin
      .from('blacklisted_tg_users')
      .select('user_id')
      .in('user_id', userIds);
    
    console.log('API: Supabase query result:', { data: blacklistedUsers, error })
    
    if (error) {
      console.error('API: Supabase error:', error)
      return NextResponse.json({ 
        success: false, 
        message: "Error checking blacklisted users" 
      }, { status: 500 });
    }
    
    const blacklistedUserIds = blacklistedUsers?.map(user => user.user_id) || [];
    console.log('API: Found blacklisted user IDs:', blacklistedUserIds)
    
    return NextResponse.json({
      success: true,
      data: blacklistedUserIds
    });
  } catch (error) {
    console.error("API: Error checking blacklisted users:", error);
    return NextResponse.json({ 
      success: false, 
      message: "Server error" 
    }, { status: 500 });
  }
} 