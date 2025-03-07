import datetime
import re
import os
import uuid
from pydantic import BaseModel, Field
from open_webui.models.files import Files
from openai import OpenAI
from markdown import markdown
from bs4 import BeautifulSoup

class FileForm(BaseModel):
    """Pydantic model to satisfy OpenWebUI, which calls .model_dump() internally."""
    id: str
    filename: str
    path: str
    meta: dict = {}

class Action:
    class Valves(BaseModel):
        TTS_VOICE: str = Field(
            default="af_sky+af_bella",
            description="The voice to use for TTS."
        )
        TTS_OUTPUT_PATH: str = Field(
            default="/app/data",
            description="The path where audio files will be saved."
        )
        TTS_URL: str = Field(
            default="http://kokoro-fastapi-cpu-service:8880/v1",
            description="The url which should be used to connect to the model."
        )

    def __init__(self):
        self.valves = self.Valves()

    def status_object(self, description="Unknown State", status="in_progress", done=False):
        return {
            "type": "status",
            "data": {
                "status": status,
                "description": description,
                "done": done,
            },
        }

    async def action(self, body: dict, __user__=None, __event_emitter__=None, __event_call__=None) -> None:
        print(f"action:{__name__}")

        try:
            if __event_emitter__:
                await __event_emitter__(self.status_object("Initializing Text-to-Speech"))

            client = OpenAI(base_url=self.valves.TTS_URL, api_key="not-needed")

            # Grab the last message (strip potential HTML/Markdown)
            last_message = body["messages"][-1]["content"].split("</details>")[-1]
            raw_last_message = self.strip_markdown_and_emojis(last_message)

            if __event_emitter__:
                await __event_emitter__(self.status_object("Generating speech"))

            if not os.path.exists(self.valves.TTS_OUTPUT_PATH):
                os.makedirs(self.valves.TTS_OUTPUT_PATH)

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"TTS_{timestamp}.mp3"
            output_path = os.path.join(self.valves.TTS_OUTPUT_PATH, filename)

            with client.audio.speech.with_streaming_response.create(
                model="kokoro",
                voice=self.valves.TTS_VOICE,
                input=raw_last_message
            ) as response:
                response.stream_to_file(output_path)

            # Insert the file into OpenWebUI's file system
            download_url = self._create_webui_download_link(
                file_path=output_path,
                file_name=filename,
                __user__=__user__,
            )

            if __event_emitter__:
                await __event_emitter__(
                    self.status_object(f"Generated successfully.", status="complete", done=True)
                )

            # Provide a clickable download link
            await __event_emitter__({
                "type": "message",
                "data": {
                    "content": f"\n\n---\n- [Download Audio]({download_url})\n"
                },
            })

        except Exception as e:
            print(f"Debug: Error in action method: {str(e)}")
            if __event_emitter__:
                await __event_emitter__(
                    self.status_object(f"Error: {str(e)}", status="error", done=True)
                )

    def _create_webui_download_link(self, file_path: str, file_name: str, __user__):
        """
        Reads the local MP3 from 'file_path' and registers it with OpenWebUI's file system.
        Returns a URL path that can be used in a clickable download link.
        """
        if not __user__ or "id" not in __user__:
            return file_path

        file_id = str(uuid.uuid4())
        meta = {
            "source": file_path,
            "title": "TTS Audio",
            "content_type": "audio/mpeg",
            "size": os.path.getsize(file_path),
            "path": file_path,
        }

        # Build the Pydantic model, including a generated id if none was provided
        file_form = FileForm(
            id=file_id,
            filename=file_name,
            path = file_path,
            meta=meta
        )

        # Insert file info into OpenWebUI
        new_file = Files.insert_new_file(__user__["id"], file_form)

        # The route returning the file content in OpenWebUI
        file_url = f"/api/v1/files/{new_file.id}/content"
        return file_url

    def strip_markdown_and_emojis(self, text: str) -> str:
        html = markdown(text)
        soup = BeautifulSoup(html, "html.parser")
        text_no_markdown = soup.get_text()

        emoji_pattern = re.compile(
            "["
            u"\U0001F600-\U0001F64F"
            u"\U0001F300-\U0001F5FF"
            u"\U0001F680-\U0001F6FF"
            u"\U0001F1E0-\U0001F1FF"
            u"\U00002500-\U00002BEF"
            u"\U00002702-\U000027B0"
            u"\U000024C2-\U0001F251"
            "]+",
            flags=re.UNICODE
        )
        return emoji_pattern.sub(r'', text_no_markdown)
