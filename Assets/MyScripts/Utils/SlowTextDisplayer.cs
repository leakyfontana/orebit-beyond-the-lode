using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TMPro;

public class SlowTextDisplayer : MonoBehaviour
{
	private string full_text = "";
	private bool full_text_displayed;
	public float max_time_until_next_char;
	private float time_until_next_char;
	private int amount_int_to_display;
	public bool show_underscore_at_end;
	private AudioManager audio_manager;
	
    // Start is called before the first frame update
    void Start()
    {
        time_until_next_char = max_time_until_next_char;
		audio_manager = FindObjectOfType<AudioManager>();
    }

    // Update is called once per frame
    void Update()
    {
		if(max_time_until_next_char == 0){
			GetComponent<TextMeshProUGUI>().text = full_text;
			full_text_displayed = true;
		}
        if (!full_text_displayed){
			time_until_next_char -= Time.unscaledDeltaTime;
			if (time_until_next_char < 0){
				time_until_next_char = max_time_until_next_char;
				if (amount_int_to_display >= full_text.Length){
					if(!show_underscore_at_end){
						GetComponent<TextMeshProUGUI>().text = full_text;
						if(amount_int_to_display % 3 == 0){
							audio_manager.PlaySoundOneShot("ComputerTypeLetter2");
						}
					}
					full_text_displayed = true;
				}
				else {
					amount_int_to_display += 1;
					GetComponent<TextMeshProUGUI>().text = full_text.Substring(0, amount_int_to_display) + "_";
					if(amount_int_to_display % 3 == 0){
						audio_manager.PlaySoundOneShot("ComputerTypeLetter2");
					}
				}
			}
		}
    }
	
	private void resetText(){
		if (full_text == ""){
			GetComponent<TextMeshProUGUI>().text = "";
		}
		else{
			GetComponent<TextMeshProUGUI>().text = "_";
		}
	}
	
	public void setText(string text){
		full_text = text;
		amount_int_to_display = 0;
		full_text_displayed = false;
		resetText();
	}
}
