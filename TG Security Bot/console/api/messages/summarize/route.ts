import { NextRequest, NextResponse } from 'next/server';
import { createServerSupabaseClient } from '@/lib/supabase-server';
import { GoogleGenerativeAI } from '@google/generative-ai';

// Initialize the Google Generative AI client
const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY || '');

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { walletAddress, messages } = body;

    if (!walletAddress) {
      return NextResponse.json(
        { success: false, message: 'Wallet address is required' },
        { status: 400 }
      );
    }

    if (!messages || !Array.isArray(messages) || messages.length === 0) {
      return NextResponse.json(
        { success: false, message: 'Valid messages array is required' },
        { status: 400 }
      );
    }

    // Verify the user has access to this chat
    const supabase = await createServerSupabaseClient();
    const { data: userData, error: userError } = await supabase
      .from('neoguard_users')
      .select('telegram_chat_id')
      .eq('wallet_address', walletAddress)
      .single();

    if (userError || !userData?.telegram_chat_id) {
      return NextResponse.json(
        { success: false, message: 'User not found or no chat ID associated' },
        { status: 403 }
      );
    }

    // Format messages for the LLM
    const formattedConversation = messages.map(msg => {
      return `${msg.user}${msg.isTeamMember ? ' (Team Member)' : ''}: ${msg.message}`;
    }).join('\n');

    // Create the prompt for the LLM
    const prompt = `
      Below is a conversation from a Telegram group chat. Please provide a concise summary of the main topics discussed, 
      key points made, and any notable interactions. Focus on the most important information and patterns in the conversation.
      
      CONVERSATION:
      ${formattedConversation}
      
      SUMMARY:
    `;

    // Generate the summary using Gemini
    const model = genAI.getGenerativeModel({ model: 'gemini-2.0-flash' });
    const result = await model.generateContent(prompt);
    const response = await result.response;
    const summary = response.text();

    // Return the summary
    return NextResponse.json({
      success: true,
      data: {
        summary
      }
    });
  } catch (error) {
    console.error('Error in message summarization:', error);
    return NextResponse.json(
      { success: false, message: 'Failed to summarize messages' },
      { status: 500 }
    );
  }
} 