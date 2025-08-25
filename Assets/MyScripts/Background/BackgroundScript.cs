using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class BackgroundScript : MonoBehaviour
{
	public Color base_color;
	public Color goal;
	private bool need_to_change_color;
	public SpriteRenderer sprite;
	
    // Start is called before the first frame update
    void Start()
    {
		sprite = GetComponent<SpriteRenderer>();
    }

    // Update is called once per frame
    void Update(){
        if(need_to_change_color){
			print("Changing color");
			print(sprite.color.r);
			print(goal.r);
			sprite.color = new Color(
				Mathf.MoveTowards(sprite.color.r, goal.r, 0.0005f),
				Mathf.MoveTowards(sprite.color.g, goal.g, 0.0005f),
				Mathf.MoveTowards(sprite.color.b, goal.b, 0.0005f)
			);
			if(sprite.color.r == goal.r && sprite.color.g == goal.g && sprite.color.b == goal.b)
				need_to_change_color = false;
		}
    }

	public void setNewGoal(Color new_goal){
		goal = new_goal;
		need_to_change_color = true;
	}
	
	public void resetBackgroundColor(){
		goal = base_color;
		need_to_change_color = true;
	}
}
