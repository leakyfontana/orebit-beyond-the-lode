using System.Collections;
using System.Collections.Generic;
using UnityEngine.Tilemaps;
using UnityEngine;
using UnityEngine.EventSystems;
using TMPro;

public class PlayerMovement : MonoBehaviour
{
	//Base movement
	[Header("Base movement")]
	float moveX = 0f;
	float moveY = 0f;
	private float base_scale_x;
	private float base_scale_y;
	public Rigidbody2D my_rigidbody;
	private Vector2 m_Velocity = Vector2.zero;
	public GameObject game_manager;
	public GameObject ui_manager_gameobject;
	private UIManager ui_manager;
	public bool can_use_mouse_control;
	public GameObject mouse_pointer_arrow;
	public bool mouse_is_last_used_input;
	[SerializeField] private float accelerationMovementSmoothing;	// How much to smooth out the acceleration movement
	[SerializeField] private float slowdownMovementSmoothing;	// How much to smooth out the slowdown movement
	private float previous_y_velocity;
	//Death
	[Header("Death")]
	public GameObject death_screen;
	public GameObject dead_player_prefab;
	//Animator
	[Header("Animator")]
	public Animator animator;
	bool isFacingRight;
	public bool isOnGround;
	public bool isFlying;
	public bool isDigging;
	private bool is_digging_side;
	private bool is_digging_bottom;
	private bool is_in_shop;
	private GameObject block_target;
	private Vector2 block_target_position;
	public GameObject dirt_particle_emitter;
	public GameObject smoke_particle_emitter;
	//Sound
	private AudioManager audio_manager;
	private float drill_clink_audio_cooldown;
	//Item use
	[Header("Item use")]
	public float max_cooldown_between_item_use;
	private float time_until_can_use_item;
	//Explosion
	[Header("Explosion")]
	public GameObject explosion_prefab;
	public GameObject explosion_without_particles_prefab;
	private float min_x;
	private float max_x;
	private float min_y;
	private float max_y;
	private bool is_creating_explosions;
	private float time_until_next_explosion_creation;
	private float total_explosion_time;
	private int number_of_explosions_per_batch;
	private int range_to_destroy_around_player;
	private (int x, int y) explosion_location;
	public GameObject dynamite_hitbox;
	public GameObject C4_hitbox;
	//Teleport
	private bool is_teleporting;
	//Background
	[Header("Background")]
	public GameObject background;
	//Bossfight
	[Header("Bossfight")]
	public bool has_bossfight_started;
	//Invincibility
	[Header("Invincibility")]
	public bool is_invincible;
	public bool is_permanently_invincible;
	public float invincibility_time;
	public float invincibility_time_left;
	public int frames_of_invisibility;
	public int frames_of_invisibility_left;
	//Popup
	[Header("Popup")]
	public GameObject popup;
	//UI Shortcuts
	[Header("UI Shortcuts")]
	public GameObject inventoryUI;
	public GameObject optionsUI;
	
	void Start(){
		ui_manager = ui_manager_gameobject.GetComponent<UIManager>();
		audio_manager = FindObjectOfType<AudioManager>();
		ui_manager.updateAllUI();
		base_scale_x = gameObject.transform.localScale.x;
		base_scale_y = gameObject.transform.localScale.y;
		audio_manager.PlaySound("IdlePlayer");
	}
	
    // Update is called once per frame
    void Update(){
		if (Input.GetKeyDown(KeyCode.I))
            inventoryUI.GetComponent<InventoryUIManager>().openUI();
        if(Input.GetKeyDown(KeyCode.Escape))
            optionsUI.GetComponent<OptionsUIManager>().openUI();			
		if(is_creating_explosions){
			time_until_next_explosion_creation -= Time.deltaTime;
			total_explosion_time -= Time.deltaTime;
			if (time_until_next_explosion_creation <= 0){
				for(int i = 0; i < number_of_explosions_per_batch; i++){
					if(!has_bossfight_started){
						GameObject explosion_object = Instantiate(explosion_prefab, new Vector3(Random.Range(min_x, max_x), Random.Range(min_y, max_y), 0), Quaternion.identity);
					}
					else{
						GameObject explosion_object = Instantiate(explosion_without_particles_prefab, new Vector3(Random.Range(min_x, max_x), Random.Range(min_y, max_y), 0), Quaternion.identity);
					}
				}
				time_until_next_explosion_creation = 0.1f;
			}
			if (total_explosion_time <= 0){
				is_creating_explosions = false;
				destroyBlocksFromExplosion(range_to_destroy_around_player);
				dynamite_hitbox.SetActive(false);
				C4_hitbox.SetActive(false);
			}
		}
		if(is_invincible){
			invincibility_time_left -= Time.deltaTime;
			frames_of_invisibility_left -= 1;
			if(frames_of_invisibility_left <= 0){
				frames_of_invisibility_left = frames_of_invisibility;
				if(GetComponent<SpriteRenderer>().color.a == 0f){
					GetComponent<SpriteRenderer>().color = new Color(1f, 1f, 1f, 1f);
				}
				else {
					GetComponent<SpriteRenderer>().color = new Color(1f, 1f, 1f, 0f);
				}
			}
			if(invincibility_time_left <= 0){
				is_invincible = false;
				frames_of_invisibility_left = 0;
				GetComponent<SpriteRenderer>().color = new Color(1f, 1f, 1f, 1f);
			}
		}
		if(time_until_can_use_item <= 0 && !is_digging_bottom && !is_digging_side && !is_in_shop && !is_teleporting){
			checkIfObjectIsPressed();
		}
		else {
			time_until_can_use_item -= Time.deltaTime;
		}
		if(drill_clink_audio_cooldown >= 0){
			drill_clink_audio_cooldown -= Time.deltaTime;
		}
        if(!is_digging_bottom && !is_digging_side && !is_in_shop && !is_teleporting){
			moveX = Input.GetAxisRaw("Horizontal") * LevelData.player_horizontal_speed;
			moveY = Input.GetAxisRaw("Vertical") * LevelData.player_vertical_speed;
			if((moveY != 0 || moveX != 0) && mouse_pointer_arrow.activeSelf){
				mouse_pointer_arrow.SetActive(false);
				mouse_is_last_used_input = false;
			}
			if(moveX == 0 && moveY == 0 && can_use_mouse_control){
				updateMousePointerRotation();
				if (!EventSystem.current.IsPointerOverGameObject()){
					Vector2 mouse_pos = Camera.main.ScreenToWorldPoint(Input.mousePosition);
					Vector2 player_pos = transform.position;
					Vector2 vec = mouse_pos - player_pos;
					float angleInDegrees = Mathf.Atan2(vec.y, vec.x) * Mathf.Rad2Deg;
					if (Input.GetMouseButton(0) && Vector2.Distance(mouse_pos, transform.position) >= 1){
						mouse_is_last_used_input = true;
						if (!mouse_pointer_arrow.activeSelf){
							mouse_pointer_arrow.SetActive(true);
						}
						moveX = Mathf.Clamp(mouse_pos.x - player_pos.x, -1, 1) * LevelData.player_horizontal_speed;
						moveY = Mathf.Clamp(mouse_pos.y - player_pos.y, -1, 1) * LevelData.player_vertical_speed;
						if(angleInDegrees < 0 && (angleInDegrees <= -105f || angleInDegrees >= -75f)){
							moveY = 0;
						}
						else if(angleInDegrees > 160 || angleInDegrees < -160){
							moveY = 0;
						}
						else if(angleInDegrees < 20 && angleInDegrees > -20){
							moveY = 0;
						}
					}
					if(Vector2.Distance(mouse_pos, transform.position) < 1 && mouse_pointer_arrow.activeSelf){
						mouse_pointer_arrow.SetActive(false);
					}
					if(Vector2.Distance(mouse_pos, transform.position) >= 1 && !mouse_pointer_arrow.activeSelf && mouse_is_last_used_input){
						mouse_pointer_arrow.SetActive(true);
					}					
				}
			}

			if(!isFlying && moveY > 0){
				isFlying = true;
				audio_manager.PlaySound("RotorPlayer");
			}
			if(isOnGround == isFlying){
				isFlying = false;
				audio_manager.StopSound("RotorPlayer");
			}

			animator.SetBool("IsFlying", isFlying);
			if(moveY < 0){
				animator.SetBool("IsStillPressingDown", true);
			}
			else{
				animator.SetBool("IsStillPressingDown", false);
			}
			if(moveY < 0 && !is_creating_explosions){
				(int x, int y) position = GetComponent<PlayerCollisions>().getBlockPositionBottomPlayer();
				if (game_manager.GetComponent<TilesManager>().doesBlockExistAndIsDiggable(position.x, position.y)){
					is_digging_bottom = true;
					block_target = game_manager.GetComponent<TilesManager>().allBlocks[(position.x, position.y)];
					if (isFacingRight){
						block_target_position = new Vector2(block_target.transform.position.x + 0.25f, block_target.transform.position.y);
					}
					else {
						block_target_position = new Vector2(block_target.transform.position.x - 0.25f, block_target.transform.position.y);
					}
					stopPlayerCollisions();
					stopMovement();
					audio_manager.PlaySound("Drill");
					transform.localRotation = Quaternion.identity;
				}
				else if (game_manager.GetComponent<TilesManager>().doesBlockExistAndIsNotDiggable(position.x, position.y)){
					if(drill_clink_audio_cooldown <= 0){
						audio_manager.PlaySoundOneShot("DrillClink");
						drill_clink_audio_cooldown = 0.25f;
					}
				}
				else {
					Debug.Log("No tile under player");
				}
			}
			else if (moveX != 0 && isOnGround && !is_creating_explosions){
				(int x, int y) position = GetComponent<PlayerCollisions>().getBlockPositionSidePlayer();
				if(game_manager.GetComponent<TilesManager>().doesBlockExistAndIsDiggable(position.x, position.y)){
					is_digging_side = true;
					block_target = game_manager.GetComponent<TilesManager>().allBlocks[(position.x, position.y)];
					if (isFacingRight && moveX > 0){
						block_target_position = new Vector2(block_target.transform.position.x + 0.25f, block_target.transform.position.y);
					}
					else if (!isFacingRight && moveX < 0){
						block_target_position = new Vector2(block_target.transform.position.x - 0.25f, transform.position.y);
					}
					else {
						cancelDig();
						Debug.Log("Player is trying to dig in a direction and moving in the opposite direction");
						return;
					}					
					transform.localRotation = Quaternion.identity;
					stopPlayerCollisions();
					stopMovement();
					FindObjectOfType<AudioManager>().PlaySound("Drill");
				}
				else if (game_manager.GetComponent<TilesManager>().doesBlockExistAndIsNotDiggable(position.x, position.y)){
					if(drill_clink_audio_cooldown <= 0){
						audio_manager.PlaySoundOneShot("DrillClink");
						drill_clink_audio_cooldown = 0.5f;
					}
				}
			}
			animator.SetFloat("HorizontalSpeed", Mathf.Abs(my_rigidbody.velocity.x));
			animator.SetFloat("VerticalSpeed", Mathf.Abs(moveY));
			animator.SetBool("IsOnGround", isOnGround && my_rigidbody.velocity.y <= 0.01);
			animator.SetBool("IsDiggingBottom", is_digging_bottom);
			animator.SetBool("IsDiggingSide", is_digging_side);
		}
		else if (is_digging_bottom || is_digging_side){
			animator.SetBool("IsDiggingBottom", is_digging_bottom);
			animator.SetBool("IsDiggingSide", is_digging_side);
			dig();
		}
		else if (is_in_shop || is_teleporting){
			animator.SetFloat("HorizontalSpeed", Mathf.Abs(my_rigidbody.velocity.x));
			animator.SetFloat("VerticalSpeed", my_rigidbody.velocity.x);
		}
		else {
			Debug.Log("Error: Movement method in player update should not have reached this branch");
		}
		//Sound pitch update
		audio_manager.ChangeSoundPitch("IdlePlayer", Mathf.Abs(my_rigidbody.velocity.x)/25);
		if(my_rigidbody.velocity.y > 0){
			audio_manager.ChangeSoundPitch("RotorPlayer", my_rigidbody.velocity.y/10);
		}
		if(block_target && Vector2.Distance(transform.position, block_target_position) > 1.5f){
			cancelDig();
			Debug.Log("Dig has been cancelled because the target position is too far away from player");
			return;
		}
    }
	
	void FixedUpdate(){
		manageCrashVerification();
		if (!is_digging_bottom && !is_digging_side && !is_in_shop && !is_teleporting){
			// Move the character on the X axis by finding the target velocity
			Vector2 targetVelocity = new Vector2(moveX, my_rigidbody.velocity.y);
			// And then smoothing it out and applying it to the character
			if (moveX == 0){
				my_rigidbody.velocity = Vector2.SmoothDamp(my_rigidbody.velocity, targetVelocity, ref m_Velocity,slowdownMovementSmoothing);			
			}
			else {
				my_rigidbody.velocity = Vector2.SmoothDamp(my_rigidbody.velocity, targetVelocity, ref m_Velocity, accelerationMovementSmoothing);			
			}

			//JE POURRAIS METTRE UNE VITESSE MAXIMALE AU RIGIDBODY QUI DEPEND DE LA PUISSANCE DE L'UPGRADE DU MOTEUR QUE J'AI POUR LE MOMENT. CA EVITERAIS D'ALLER BLINDE VITE
			//Debug.Log(my_rigidbody.velocity.y);
			if(moveY > 0 && my_rigidbody.velocity.y < 1 * LevelData.player_vertical_speed){ //ICI JE DOIS MULTIPLIER LE 2 PAR L'UPGRADE DE ROTOR QUE J'AI
				my_rigidbody.AddForce (new Vector2(0, moveY * Time.fixedDeltaTime * 200));			
			}
			
			//Flip the player character if needed
			if (moveX > 0 && !isFacingRight){
				animator.SetBool("NeedsFlipping", true);
				smoke_particle_emitter.GetComponent<ParticleSystem>().Stop();
			}
			else if (moveX < 0 && isFacingRight){
				animator.SetBool("NeedsFlipping", true);
				smoke_particle_emitter.GetComponent<ParticleSystem>().Stop();
			}
			var rot = transform.localRotation.eulerAngles;
			if(isFlying){ //Rotate when flying
				if (moveX == 0){
					rot.Set(0, 0, Mathf.MoveTowardsAngle(rot.z, 0, 0.4f));
				}
				else if (moveX < 0){
					rot.Set(0, 0, Mathf.MoveTowardsAngle(rot.z, 10, -0.5f * my_rigidbody.velocity.x));
				}
				else if (moveX > 0){
					rot.Set(0, 0, Mathf.MoveTowardsAngle(rot.z, -10, 0.5f * my_rigidbody.velocity.x));
				}
			}
			else {
				rot.Set(0, 0, Mathf.MoveTowardsAngle(rot.z, 0, 0.4f));
			}
			transform.localRotation = Quaternion.Euler(rot);
		}
		updateFuel();
	}
	
	private void manageCrashVerification(){
		float new_vel = Mathf.Abs(my_rigidbody.velocity.y);
		if(new_vel < previous_y_velocity - 7){
			loseHP((int) (0.5f * previous_y_velocity));
		}
		previous_y_velocity = new_vel;
	}
	
	public void dig(){ //DIGGING IS WAY TOO FAST, I HAVE TO SLOW IT DOWN
		float step = 0.4f * LevelData.player_dig_speed * Time.deltaTime * getDepthModifier(Mathf.FloorToInt(transform.position.y));
		transform.position = Vector2.MoveTowards(transform.position, block_target_position, step);
		updateMousePointerRotation();
		if (Vector2.Distance(transform.position, block_target_position) < 0.5f && !game_manager.GetComponent<TilesManager>().blockChangedTexture){
			int desired_orientation = 0;
			int previous_x = block_target.GetComponent<BlockData>().map_x;
			int previous_y = block_target.GetComponent<BlockData>().map_y;
			if(is_digging_bottom){
				desired_orientation = 2;
				previous_y -= 1;
			}
			else if(is_digging_side){ //It means the player is digging to the side
				if(isFacingRight){
					desired_orientation = 3;
					previous_x -= 1;
				}
				else{
					desired_orientation = 1;
					previous_x += 1;
				}
			}
			else{
				Debug.Log("ERROR: Player is in dig method while is_digging_bottom and is_digging_side are both false");
				cancelDig();
			}
			if(block_target.GetComponent<BlockData>().object_name == "Lava")
				audio_manager.PlaySoundOneShot("Lava");
			game_manager.GetComponent<TilesManager>().halfwayDigBlock(block_target, previous_y, previous_x, desired_orientation);
		}
		if (Vector2.Distance(transform.position, block_target_position) < 0.05f){
			print("Digged dug");
			string mineral_name = block_target.GetComponent<BlockData>().object_name;
			if (LevelData.minerals_name_list.Contains(mineral_name)){
				if(LevelData.addMineralInCargo(mineral_name)){
					createPopup("+1 " + mineral_name, "IsMineral");
				} else {
					createPopup("Cargo is full!\nYou lost " + mineral_name, "IsWarning");
				}
				audio_manager.PlaySoundOneShot("MineralGet");
			}
			else if (LevelData.treasure_name_list.Contains(mineral_name)){
				createPopup("+1 " + mineral_name + "\n+$" + LevelData.minerals[mineral_name].ore_value, "IsMineral");
				LevelData.addTreasureInCargo(mineral_name);
				audio_manager.PlaySoundOneShot("MineralGet");
			}
			if(block_target.GetComponent<BlockData>().object_name == "Lava")
				loseHP((int) (45 * (1-LevelData.player_radiator))); //This is the correct amount of damage
			game_manager.GetComponent<TilesManager>().digBlock(block_target);
			is_digging_side = false;
			is_digging_bottom = false;
			block_target = null;
			block_target_position = Vector2.zero;
			startPlayerCollisions();
			ui_manager.updateMoneyUI();
			startMovement();
			audio_manager.StopSound("Drill");
			cancelVelocity();
		}
	}
	
	public void cancelDig(){
		Debug.Log("EMERGENCY DIG CANCEL");
		is_digging_side = false;
		is_digging_bottom = false;
		block_target = null;
		block_target_position = Vector2.zero;
		startPlayerCollisions();
		ui_manager.updateMoneyUI();
		startMovement();
		audio_manager.StopSound("Drill");
	}
	
	public void updateMousePointerRotation(){
		Vector2 mouse_pos = Camera.main.ScreenToWorldPoint(Input.mousePosition);
		Vector2 player_pos = transform.position;
		Vector2 vec = mouse_pos - player_pos;
		float angleInDegrees = Mathf.Atan2(vec.y, vec.x) * Mathf.Rad2Deg;
		mouse_pointer_arrow.transform.rotation = Quaternion.Euler(0, 0, angleInDegrees - 90);
	}
	
	public void flipCharacter(){
		Vector3 currentScale = gameObject.transform.localScale;
		currentScale.x *= -1;
		gameObject.transform.localScale = currentScale;
		isFacingRight = !isFacingRight;
		smoke_particle_emitter.GetComponent<ParticleSystem>().Play();
		updateMousePointerRotation();
		GameObject[] popups = GameObject.FindGameObjectsWithTag("PlayerPopup");
		foreach(GameObject popup in popups){
			currentScale = popup.transform.localScale;
			currentScale.x *= -1;
			popup.transform.localScale = currentScale;
		}
	}
	
	private void stopMovement(){
		GetComponent<Rigidbody2D>().bodyType = RigidbodyType2D.Static;
	}
	
	private void startMovement(){
		GetComponent<Rigidbody2D>().bodyType = RigidbodyType2D.Dynamic;
	}
	
	private float getDepthModifier(int position_y){ //Il faut que je m'assure que le depth modifier fonctionne bien
		int max = 600;
		float current = Mathf.Abs(position_y);
		float depth_percent = current/max;
		float modifier = 0.1f + 0.9f * (1 - depth_percent); //Base speed modifier, and moving speed modifier. Total has to == 1
		return modifier;
	}
	
	public void startPlayerCollisions(){
		foreach(Collider2D collider in GetComponents<Collider2D>()){
			collider.enabled = true;
		}
		dirt_particle_emitter.gameObject.GetComponent<ParticleSystem>().Stop();
	}

	public void stopPlayerCollisions(){
		foreach(Collider2D collider in GetComponents<Collider2D>()){
			collider.enabled = false;
		}
		dirt_particle_emitter.GetComponent<ParticleSystem>().Play();
	}
	
	public void updateFuel(){
		if (is_digging_bottom || is_digging_side){
			LevelData.player_fuel -= (0.33f * Time.deltaTime); //Apply the reduction two times when digging
			ui_manager.updateFuelUI();
		}
		else if(moveX != 0 || moveY > 0){
			LevelData.player_fuel -= (0.16f * Time.deltaTime);
			ui_manager.updateFuelUI();
		}
		else{
			LevelData.player_fuel -= (0.08f * Time.deltaTime);
			ui_manager.updateFuelUI();
		}
		if (LevelData.player_fuel <= 0){
			killPlayer();
		}
	}
	
	public void enterShop(){
		cancelVelocity();
		is_in_shop = true;
		Time.timeScale = 0f;
		audio_manager.PauseSounds();
	}

	public void exitShop(){
		is_in_shop = false;
		Time.timeScale = 1f;
		audio_manager.ResumeSounds();
	}
	
	public void cancelVelocity(){
		if(!(my_rigidbody.bodyType == RigidbodyType2D.Static)){
			my_rigidbody.velocity = Vector3.zero;
			my_rigidbody.angularVelocity = 0f;
		}
	}
	
	private void checkIfObjectIsPressed(){
		if(Input.GetKeyDown(KeyCode.Alpha1)){
			print("Fuel tank");
			time_until_can_use_item = max_cooldown_between_item_use;
			if (LevelData.player_items["Reserve Fuel Tank"] > 0){
				LevelData.player_items["Reserve Fuel Tank"] -= 1;
				LevelData.addFuel(25);
				ui_manager.updateFuelUI();
				audio_manager.PlaySoundOneShot("Refuel");
				createPopup("Used Reserve Fuel Tank", "IsObject");
			}
			else{
				createPopup("No Reserve Fuel Tank", "IsWarning");
				audio_manager.PlaySoundOneShot("NoItemAvailable");
			}
		}
		else if(Input.GetKeyDown(KeyCode.Alpha2)){
			print("Repair Nanobots");
			time_until_can_use_item = max_cooldown_between_item_use;
			if (LevelData.player_items["Hull Repair Nanobots"] > 0){
				LevelData.player_items["Hull Repair Nanobots"] -= 1;
				ui_manager.updateHullUI();
				LevelData.addHull(30 * 15); //15 dollars = 1 HP
				audio_manager.PlaySoundOneShot("Nanobots");
				createPopup("Used Hull Repair Nanobots", "IsObject");
			}
			else{
				createPopup("No Hull Repair Nanobots", "IsWarning");
				audio_manager.PlaySoundOneShot("NoItemAvailable");
			}
		}
		else if(Input.GetKeyDown(KeyCode.Alpha3)){
			print("Dynamite");
			time_until_can_use_item = max_cooldown_between_item_use;
			if (LevelData.player_items["Dynamite"] > 0){
				LevelData.player_items["Dynamite"] -= 1;
				createExplosions(1, 0.5f, 8);
				audio_manager.PlaySoundOneShot("Dynamite");
				dynamite_hitbox.SetActive(true);
				createPopup("Used Dynamite", "IsObject");
			}
			else{
				createPopup("No Dynamite", "IsWarning");
				audio_manager.PlaySoundOneShot("NoItemAvailable");
			}
		}
		else if(Input.GetKeyDown(KeyCode.Alpha4)){
			print("Plastic Explosives");
			time_until_can_use_item = max_cooldown_between_item_use;
			if (LevelData.player_items["Plastic Explosives"] > 0){
				LevelData.player_items["Plastic Explosives"] -= 1;
				createExplosions(2, 0.7f, 15);	
				audio_manager.PlaySoundOneShot("C4");
				C4_hitbox.SetActive(true);
				createPopup("Used Plastic Explosives", "IsObject");
			}
			else{
				createPopup("No Plastic Explosives", "IsWarning");
				audio_manager.PlaySoundOneShot("NoItemAvailable");
			}
		}
		else if(Input.GetKeyDown(KeyCode.Alpha5)){
			print("Quantum Teleporter");
			time_until_can_use_item = max_cooldown_between_item_use;
			if(has_bossfight_started){
				createPopup("Cannot teleport", "IsWarning");
				audio_manager.PlaySoundOneShot("NoItemAvailable");				
			}
			else if (LevelData.player_items["Quantum Teleporter"] > 0){
				LevelData.player_items["Quantum Teleporter"] -= 1;
				animator.SetTrigger("TeleportDangerous");
				is_teleporting = true;
				stopMovement();
				audio_manager.PlaySoundOneShot("QuantumTeleporter");
				createPopup("Used Quantum Teleporter", "IsObject");
				background.GetComponent<BackgroundScript>().resetBackgroundColor();
			}
			else{
				createPopup("No Quantum Teleporter", "IsWarning");
				audio_manager.PlaySoundOneShot("NoItemAvailable");
			}
		}
		else if(Input.GetKeyDown(KeyCode.Alpha6)){
			print("Matter Transmitter");
			time_until_can_use_item = max_cooldown_between_item_use;
			if(has_bossfight_started){
				createPopup("Cannot teleport", "IsWarning");
				audio_manager.PlaySoundOneShot("NoItemAvailable");				
			}
			else if (LevelData.player_items["Matter Transmitter"] > 0){
				LevelData.player_items["Matter Transmitter"] -= 1;
				animator.SetTrigger("TeleportSafe");
				is_teleporting = true;
				stopMovement();
				audio_manager.PlaySoundOneShot("MatterTransmitter");
				createPopup("Used Matter Transmitter", "IsObject");
				background.GetComponent<BackgroundScript>().resetBackgroundColor();
			}
			else{
				createPopup("No Matter Transmitter", "IsWarning");
				audio_manager.PlaySoundOneShot("NoItemAvailable");
			}
		}
	}
	
	public void createPopup(string text, string trigger_text){
		GameObject my_popup = Instantiate(popup, new Vector3(0, 0, 0), Quaternion.identity);
		my_popup.transform.SetParent(transform);
		my_popup.GetComponent<Animator>().SetTrigger(trigger_text);
		my_popup.GetComponent<TextMeshPro>().text = text;
	}

	
	public void createExplosions(float range, float time, int quantity){
		explosion_location = ((int) Mathf.Floor(Mathf.Abs(transform.position.x)),(int) Mathf.Floor(Mathf.Abs(transform.position.y)) + 1);
		total_explosion_time = time;
		min_x = transform.position.x - range - 0.5f;
		max_x = transform.position.x + range + 0.5f;
		min_y = transform.position.y - range - 0.5f;
		max_y = transform.position.y + range + 0.5f;
		time_until_next_explosion_creation = 0f;
		is_creating_explosions = true;
		number_of_explosions_per_batch = quantity;
		range_to_destroy_around_player = (int) range;
	}
	
	public void destroyBlocksFromExplosion(int range){
		int base_x = explosion_location.x;
		int base_y = explosion_location.y;
		int min_x = base_x - range;
		int max_x = base_x + range + 1;
		int min_y = base_y - range;
		int max_y = base_y + range + 1;
		if (min_x < 0)
			min_x = 0;
		if (max_x >= LevelData.earthWidth)
			max_x = LevelData.earthWidth;
		if (min_y < 0)
			min_y = 0;
		if (max_y >= LevelData.earthHeight)
			max_y = LevelData.earthHeight;
		for (int i = min_x; i < max_x; i++){
			for (int j = min_y; j < max_y; j++){
				GameObject block = game_manager.GetComponent<TilesManager>().allBlocks[(i, j)];
				game_manager.GetComponent<TilesManager>().instantDigBlock(block);
			}
		}
	}
	
	public void teleportPlayerSafe(){
		transform.position = new Vector3(5.5f, -3.5f, 0f);
		print("Teleporting player safe");
		//Teleport coordinates 5.5, -3.5
	}
	
	public void endTeleportPlayerSafe(){
		startMovement();
		is_teleporting = false;
		print("Finishing teleporting player safe");
		/*Vector3 currentScale = gameObject.transform.localScale;
		currentScale.x = base_scale_x;
		currentScale.y = base_scale_y;
		gameObject.transform.localScale = currentScale;*/
	}

	public void teleportPlayerDangerous(){
		transform.position = new Vector3(5.5f, -1.5f, 0f);
		//Teleport coordinates 5.5, -2.5
	}
	
	public void endTeleportPlayerDangerous(){
		print("Finishing teleporting player dangerous");
		startMovement();
		is_teleporting = false;
		my_rigidbody.velocity = new Vector3(Random.Range(-6f,6f), (Random.value < 0.6? -5f: 10f), 0f); //Maybe I should put the -5f a little higher, it will depend on damage taken on impact from high speed
	}
	
	public void loseHP(int amount){
		if(!is_invincible && !is_permanently_invincible){
			audio_manager.PlaySound("PlayerCrash");
			LevelData.player_hp -= amount;
			if (LevelData.player_hp <= 0){
				killPlayer();
			}
			else {
				is_invincible = true;
				invincibility_time_left = invincibility_time;
			}
			ui_manager.updateHullUI();			
		}
	}
	
	public void gainHP(int amount){
		LevelData.player_hp = Mathf.Min(LevelData.player_hp + amount, LevelData.player_max_hp);
		if (LevelData.player_hp <= 0){
			killPlayer();
		}
		ui_manager.updateHullUI();
	}
	
	public void killPlayer(){
		audio_manager.PlaySoundOneShot("KillPlayer");
		audio_manager.StopSound("LowFuelWarning");
		audio_manager.StopSound("VeryLowFuelWarning");
		audio_manager.StopSound("Drill");
		audio_manager.StopSound("IdlePlayer");
		audio_manager.StopSound("RotorPlayer");
		death_screen.SetActive(true);
		Instantiate(dead_player_prefab, transform.position, Quaternion.identity);
		Destroy(gameObject);
	}
}
